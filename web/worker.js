// The whole of flab2bp, running in one Web Worker.
//
// Three wasm modules live here side by side: CPython (Pyodide), or-tools'
// CP-SAT runtime and or-tools' MPSolver runtime.  Python is the application --
// the unmodified flab2bp package, doing every bit of parsing, rate maths,
// layout, validation and blueprint encoding -- and the two or-tools runtimes
// are called only where flab2bp would have called libortools.
//
// The awkward part is that the or-tools runtimes are asynchronous: they are
// built with emscripten pthreads, so a solve returns a Promise.  flab2bp calls
// `solver.solve(model)` from the bottom of a deep synchronous call stack and
// cannot be made to await.  JSPI closes that gap: the Python entry point is
// invoked with `callPromising()`, which puts it on a suspendable stack, and
// `pyodide.ffi.run_sync` then blocks that stack on a JS promise without
// blocking the worker.  That is why this page needs a browser with
// WebAssembly stack switching, and why the solvers need cross-origin
// isolation (their pthread pool needs SharedArrayBuffer).

const PYODIDE_DIR = './vendor/pyodide/';
const PACKAGES = ['micropip', 'numpy', 'pandas', 'sympy', 'pydantic', 'protobuf'];

let pyodide = null;
let entryPoint = null;
let CpSat = null;
let loadMPSolverRuntime = null;
let mpModule = null;

const post = (type, payload) => self.postMessage({ type, ...payload });
const stage = (text) => post('stage', { text });

function readU32(buffer, ptr) {
  return new DataView(buffer).getUint32(ptr, true);
}

async function mpSolve(requestBytes) {
  if (mpModule === null) mpModule = await loadMPSolverRuntime();
  const module = mpModule;
  const requestPtr = module._malloc(requestBytes.length || 1);
  module.HEAPU8.set(requestBytes, requestPtr);
  const lenPtr = module._malloc(4);
  let responsePtr = 0;
  try {
    responsePtr = await module.cwrap('mp_solver_solve_model_request', 'number', [
      'number',
      'number',
      'number',
    ])(requestPtr, requestBytes.length, lenPtr);
    const len = readU32(module.HEAPU8.buffer, lenPtr);
    const out = module.HEAPU8.slice(responsePtr, responsePtr + len);
    return out;
  } finally {
    module._free(requestPtr);
    module._free(lenPtr);
    if (responsePtr) module._free_buffer(responsePtr);
  }
}

// `pipeline.build`'s progress sink, forwarded straight to the page. The server
// arm gets the same sequence out of `jobs.Job.settled` and a poll; here the
// solve is on a suspendable stack, so it can call out synchronously and the
// page hears about each pair as it settles rather than at the end.
self.__flabProgress = (json) => post('progress', { step: JSON.parse(json) });

// The single seam. `ortools._wasm_bridge` calls this and nothing else.
self.__flabSolverBridge = async (kind, payload) => {
  const request = new Uint8Array(payload);
  if (kind === 'cp_sat_solve') {
    const modelLen = readU32(request.buffer, request.byteOffset);
    const model = request.subarray(4, 4 + modelLen);
    const params = request.subarray(4 + modelLen);
    return CpSat.solveRaw(model, params.length ? params : null);
  }
  if (kind === 'cp_sat_validate') {
    const verdict = await CpSat.validate(request);
    return new TextEncoder().encode(verdict.ok ? '' : verdict.message);
  }
  if (kind === 'mp_solve') {
    return mpSolve(request);
  }
  throw new Error(`unknown solver bridge kind: ${kind}`);
};

async function boot() {
  const t0 = performance.now();
  stage('loading Pyodide');
  const { loadPyodide } = await import(`${PYODIDE_DIR}pyodide.mjs`);
  pyodide = await loadPyodide({ indexURL: PYODIDE_DIR });
  const tPyodide = performance.now();

  stage('loading numpy / pandas / sympy / pydantic / protobuf');
  await pyodide.loadPackage(PACKAGES);
  const tPackages = performance.now();

  stage('loading the or-tools wasm solvers');
  ({ CpSat } = await import('./vendor/ortools/browser/cp-sat.js'));
  ({ loadMPSolverRuntime } = await import('./vendor/ortools/browser/runtime_loader.js'));

  stage('installing the ortools shim and flab2bp');
  // Checked rather than assumed. A static server answers a missing file with
  // whatever its 404 body is, and `.json()` on an HTML error page raises a
  // syntax error that names a character offset instead of the missing build
  // step. This is the exact failure that a shared `web/dist` used to produce
  // every time the server arm rebuilt its front end.
  const manifestResponse = await fetch('./payload/manifest.json');
  if (!manifestResponse.ok) {
    throw new Error(
      `web/payload/manifest.json is missing (HTTP ${manifestResponse.status}). ` +
        'Run:  python web/build_payload.py',
    );
  }
  const manifest = await manifestResponse.json();
  const shim = new Uint8Array(await (await fetch(`./payload/${manifest.pyshim}`)).arrayBuffer());
  await pyodide.unpackArchive(shim, 'zip', { extractDir: '/pyshim' });
  // Ahead of everything: `import ortools` must find the shim, never a wheel.
  pyodide.runPython("import sys; sys.path.insert(0, '/pyshim')");

  const micropip = pyodide.pyimport('micropip');
  // deps=False on purpose. flab2bp's declared dependencies are ortools (the
  // shim), httpx and nodriver (both imported lazily and both for the network
  // paths a static page does not have), and sympy/pydantic which are already
  // loaded. Letting micropip resolve them would mean reaching PyPI at solve
  // time, which is exactly what this arm is claiming not to do.
  await micropip.install.callKwargs(`./payload/${manifest.wheel}`, { deps: false });

  stage('importing flab2bp');
  const bootstrap = await (await fetch('./bootstrap.py')).text();
  pyodide.runPython(bootstrap);
  entryPoint = pyodide.globals.get('solve');
  const tReady = performance.now();

  post('ready', {
    timings: {
      pyodideMs: Math.round(tPyodide - t0),
      packagesMs: Math.round(tPackages - tPyodide),
      importMs: Math.round(tReady - tPackages),
      totalMs: Math.round(tReady - t0),
    },
    crossOriginIsolated: self.crossOriginIsolated,
    sharedArrayBuffer: typeof SharedArrayBuffer !== 'undefined',
    jspi: typeof WebAssembly.Suspending === 'function',
    hardwareConcurrency: navigator.hardwareConcurrency,
  });
}

self.onmessage = async (event) => {
  const message = event.data;
  try {
    if (message.type === 'boot') {
      await boot();
    } else if (message.type === 'solve') {
      const started = performance.now();
      // callPromising is what makes run_sync legal inside: it runs Python on a
      // suspendable stack.
      const json = await entryPoint.callPromising(JSON.stringify(message.options));
      // A job snapshot, shaped exactly like the server arm's
      // `GET /api/build/<id>` body -- see web/bootstrap.py.
      post('result', {
        snapshot: JSON.parse(json),
        wallMs: Math.round(performance.now() - started),
      });
    }
  } catch (error) {
    post('fatal', { error: String(error?.stack ? error.stack : error) });
  }
};
