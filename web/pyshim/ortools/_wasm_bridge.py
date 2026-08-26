"""The one place Python hands bytes to a solver that is not in this process.

Both stand-ins -- ``sat.python.swig_helper`` for CP-SAT and
``linear_solver.pywraplp`` for SCIP -- go through here, and neither of them
knows what is on the other side.  The host page installs a callable; if it has
not, every solve raises.  There is deliberately no in-process fallback: a
"solver" that quietly answered without a solver would be the worst possible
failure mode for this project, so the absence of a bridge is an error and says
so.

The callable is synchronous from Python's point of view.  Under Pyodide the
wasm solvers are asynchronous (they run on emscripten pthreads), so the page
bridges the two with JSPI -- ``pyodide.ffi.run_sync`` inside a Python entry
point invoked as ``callPromising()``.  That detail belongs to the page, not
here.
"""

from __future__ import annotations

from collections.abc import Callable

#: ``(kind, request_bytes) -> response_bytes``.  ``kind`` is one of
#: ``"cp_sat_solve"``, ``"cp_sat_validate"`` or ``"mp_solve"``.
SolverBridge = Callable[[str, bytes], bytes]

_bridge: SolverBridge | None = None


class NoSolverBridge(RuntimeError):
    """Raised when a solve is attempted with no wasm solver wired up."""


def set_bridge(bridge: SolverBridge | None) -> None:
    global _bridge
    _bridge = bridge


def has_bridge() -> bool:
    return _bridge is not None


def call(kind: str, request: bytes) -> bytes:
    if _bridge is None:
        raise NoSolverBridge(
            f"no wasm solver bridge is installed, so {kind!r} cannot run. "
            "The page must call ortools._wasm_bridge.set_bridge(...) before "
            "any solve; there is no in-process solver to fall back to."
        )
    response = _bridge(kind, request)
    if not isinstance(response, (bytes, bytearray, memoryview)):
        raise TypeError(
            f"the solver bridge returned {type(response).__name__}, not bytes, for {kind!r}"
        )
    return bytes(response)
