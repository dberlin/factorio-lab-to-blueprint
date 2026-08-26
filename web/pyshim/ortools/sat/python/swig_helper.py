"""Pure-Python stand-in for ortools 9.11's ``sat.python.swig_helper``.

Upstream this module is the pybind layer over ``libortools``: ``SolveWrapper``
owns a C++ solve and ``CpSatHelper`` exposes the model utilities.  Here it is
the seam.  ``SolveWrapper.solve`` serialises the ``CpModelProto`` and the
``SatParameters`` the caller configured, hands both to the wasm CP-SAT build
through ``ortools._wasm_bridge``, and parses the ``CpSolverResponse`` that
comes back with the same generated protobuf code ortools ships.

Nothing is reimplemented: the model that reaches the solver is byte-for-byte
the model ortools' own ``cp_model.py`` built, and the answer that reaches
flab2bp is byte-for-byte the solver's response.

The callbacks upstream supports (per-solution, log, best-bound) are not wired
up.  flab2bp uses none of them, and a callback that silently never fired would
be a lie about the search, so asking for one raises.
"""

from __future__ import annotations

from collections.abc import Callable

from ortools import _wasm_bridge
from ortools.sat import cp_model_pb2, sat_parameters_pb2

__all__ = ["CpSatHelper", "SolutionCallback", "SolveWrapper"]


class SolutionCallback:
    """The base class ``CpSolverSolutionCallback`` inherits from.

    It exists so that ``cp_model.py`` imports and subclasses cleanly.  A
    callback instance can be constructed; it simply never gets called, because
    ``SolveWrapper`` refuses to accept one.
    """

    def __init__(self) -> None:
        self._solution: cp_model_pb2.CpSolverResponse | None = None

    def OnSolutionCallback(self) -> None:  # noqa: N802 - upstream's name
        """Overridden by user subclasses."""


class SolveWrapper:
    """One CP-SAT solve, executed by the wasm build."""

    def __init__(self) -> None:
        self._parameters = sat_parameters_pb2.SatParameters()

    def set_parameters(self, parameters: sat_parameters_pb2.SatParameters) -> None:
        self._parameters.CopyFrom(parameters)

    def solve(self, model_proto: cp_model_pb2.CpModelProto) -> cp_model_pb2.CpSolverResponse:
        request = cp_model_pb2.CpModelProto()
        request.CopyFrom(model_proto)
        payload = _pack(request.SerializeToString(), self._parameters.SerializeToString())
        raw = _wasm_bridge.call("cp_sat_solve", payload)
        response = cp_model_pb2.CpSolverResponse()
        response.ParseFromString(raw)
        return response

    # -- the parts flab2bp does not use, which therefore must not pretend ----

    def add_solution_callback(self, callback: SolutionCallback) -> None:
        raise NotImplementedError(
            "the wasm CP-SAT bridge does not deliver per-solution callbacks; "
            "a callback that never fires would misreport the search"
        )

    def clear_solution_callback(self, callback: SolutionCallback) -> None:
        return None

    def add_log_callback(self, callback: Callable[[str], None]) -> None:
        raise NotImplementedError("the wasm CP-SAT bridge does not stream the solver log")

    def add_best_bound_callback(self, callback: Callable[[float], None]) -> None:
        raise NotImplementedError("the wasm CP-SAT bridge does not stream best-bound updates")

    def stop_search(self) -> None:
        raise NotImplementedError(
            "the wasm CP-SAT bridge runs one solve to completion; there is no "
            "second thread from which to interrupt it"
        )


class CpSatHelper:
    """Model utilities.  Only ``validate_model`` has a wasm counterpart."""

    @staticmethod
    def validate_model(model_proto: cp_model_pb2.CpModelProto) -> str:
        raw = _wasm_bridge.call("cp_sat_validate", model_proto.SerializeToString())
        return raw.decode("utf-8")

    @staticmethod
    def model_stats(model_proto: cp_model_pb2.CpModelProto) -> str:
        # There IS a `CpSat.modelStats` in `vendor/ortools/browser/cp-sat.js`,
        # and it is a trap. Read it: it decodes the proto with protobufjs in
        # JavaScript and returns `{name, variables, constraints, hasObjective}`
        # as JSON. libortools' `CpModelStats` is a multi-line text report about
        # the presolved model -- constraint breakdown by type, domain sizes,
        # the objective's terms. They share a name and nothing else, and
        # returning the first where a caller expects the second would be a
        # different thing wearing the right label.
        raise NotImplementedError(
            "model_stats is libortools' CpModelStats text report, and the wasm "
            "build has no entry point for it. (`CpSat.modelStats` in the vendored "
            "JS is an unrelated protobufjs summary -- variable and constraint "
            "COUNTS as JSON -- and is not this.)"
        )

    @staticmethod
    def solver_response_stats(response: cp_model_pb2.CpSolverResponse) -> str:
        # Checked in the vendored bundle: no `solverResponseStats`, no
        # `responseStats` on CpSat, nothing under any spelling.
        raise NotImplementedError(
            "solver_response_stats is a libortools formatter with no wasm entry point"
        )

    @staticmethod
    def write_model_to_file(model_proto: cp_model_pb2.CpModelProto, filename: str) -> bool:
        raise NotImplementedError("there is no filesystem to write a model to")


def _pack(model: bytes, parameters: bytes) -> bytes:
    """``[u32 model length][model][parameters]``.

    The bridge carries one byte string, and CP-SAT needs two: the model and the
    parameters.  Length-prefixing keeps the JS side from having to know either
    schema -- it slices and forwards.
    """
    return len(model).to_bytes(4, "little") + model + parameters
