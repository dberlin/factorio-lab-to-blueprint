"""Pure-Python stand-in for ortools' ``pywraplp``, backed by the wasm MPSolver.

Unlike CP-SAT there is no pure-Python upstream to vendor: ``pywraplp`` is SWIG
over ``libortools`` all the way down, and the model is built in C++.  So this
module builds the same thing ortools would have built -- an ``MPModelRequest``
carrying an ``MPModelProto`` -- using ortools' *own* generated
``linear_solver_pb2``, and hands it to ``or-tools-wasm``'s MPSolver runtime,
which has SCIP compiled in.

The surface is deliberately only what ``flab2bp.rates.solve`` uses:
``CreateSolver``, ``NumVar``, ``IntVar``, ``infinity``, ``Add``, ``Sum``,
``Minimize``, ``SetTimeLimit``, ``Solve`` and ``solution_value``.  Anything
else raises rather than guessing, because the failure mode this module could
have is a silently different linear program, and a missing method is a much
better outcome than a plausible wrong answer.

The linear-expression algebra is the one genuinely reimplemented part.
``tests/clientside/test_ortools_shim.py`` builds the same programs through
this module and through the real ``pywraplp``, exports both models, and
asserts they are byte-identical protos -- so a divergence in the algebra is a
test failure and not a quietly different factory.

Expressions are keyed by variable *index*, never by the ``Variable`` object.
``Variable.__eq__`` builds a constraint rather than answering a question, so a
``Variable`` in a dict would make an ordinary hash-bucket collision raise.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from ortools import _wasm_bridge
from ortools.linear_solver import linear_solver_pb2 as pb

__all__ = ["Solver"]

#: MPSolver's infinity is a real IEEE infinity, not DBL_MAX.  Writing DBL_MAX
#: into the proto is not wrong arithmetically but it is a *different* bound
#: than the one real pywraplp writes, and the differential test says so.
INFINITY = math.inf

#: ortools' own name -> ``MPModelRequest.SolverType``.  Only the ones the wasm
#: build actually has are listed; asking for anything else returns ``None``
#: from ``CreateSolver``, exactly as ortools does for a backend it lacks.
_SOLVER_TYPES = {
    "GLOP": pb.MPModelRequest.GLOP_LINEAR_PROGRAMMING,
    "CLP": pb.MPModelRequest.CLP_LINEAR_PROGRAMMING,
    "SCIP": pb.MPModelRequest.SCIP_MIXED_INTEGER_PROGRAMMING,
    "CBC": pb.MPModelRequest.CBC_MIXED_INTEGER_PROGRAMMING,
    "SAT": pb.MPModelRequest.SAT_INTEGER_PROGRAMMING,
}


class LinearExpr:
    """An affine combination of variables: ``sum(coeff * var) + constant``."""

    __slots__ = ("constant", "terms")

    def __init__(self, terms: dict[int, float] | None = None, constant: float = 0.0) -> None:
        #: variable index -> coefficient
        self.terms: dict[int, float] = dict(terms or {})
        self.constant = float(constant)

    @staticmethod
    def _coerce(other: object) -> LinearExpr:
        if isinstance(other, LinearExpr):
            return other
        if isinstance(other, (int, float)):
            return LinearExpr(constant=float(other))
        raise TypeError(f"not a linear expression: {other!r}")

    def _combine(self, other: object, sign: float) -> LinearExpr:
        rhs = LinearExpr._coerce(other)
        terms = dict(self.terms)
        for index, coefficient in rhs.terms.items():
            terms[index] = terms.get(index, 0.0) + sign * coefficient
        return LinearExpr(terms, self.constant + sign * rhs.constant)

    def __add__(self, other: object) -> LinearExpr:
        return self._combine(other, 1.0)

    __radd__ = __add__

    def __sub__(self, other: object) -> LinearExpr:
        return self._combine(other, -1.0)

    def __rsub__(self, other: object) -> LinearExpr:
        return LinearExpr._coerce(other)._combine(self, -1.0)

    def __neg__(self) -> LinearExpr:
        return LinearExpr({i: -c for i, c in self.terms.items()}, -self.constant)

    def __mul__(self, other: object) -> LinearExpr:
        if not isinstance(other, (int, float)):
            raise TypeError("a linear expression may only be scaled by a number")
        factor = float(other)
        return LinearExpr({i: c * factor for i, c in self.terms.items()}, self.constant * factor)

    __rmul__ = __mul__

    def __truediv__(self, other: object) -> LinearExpr:
        if not isinstance(other, (int, float)):
            raise TypeError("a linear expression may only be divided by a number")
        return self.__mul__(1.0 / float(other))

    # -- comparisons build constraints, they do not answer questions ---------

    def __le__(self, other: object) -> LinearConstraint:
        return LinearConstraint(self._combine(other, -1.0), -INFINITY, 0.0)

    def __ge__(self, other: object) -> LinearConstraint:
        return LinearConstraint(self._combine(other, -1.0), 0.0, INFINITY)

    def __eq__(self, other: object) -> LinearConstraint:  # type: ignore[override]
        return LinearConstraint(self._combine(other, -1.0), 0.0, 0.0)

    def __hash__(self) -> int:
        return id(self)

    def __repr__(self) -> str:
        parts = [f"{c:+g}*x{i}" for i, c in sorted(self.terms.items())]
        if self.constant:
            parts.append(f"{self.constant:+g}")
        return "LinearExpr(" + " ".join(parts) + ")"


class Variable(LinearExpr):
    """A single decision variable, usable anywhere an expression is."""

    __slots__ = ("_index", "_name", "_solver")

    def __init__(self, solver: Solver, index: int, name: str) -> None:
        super().__init__({index: 1.0})
        self._solver = solver
        self._index = index
        self._name = name

    def index(self) -> int:
        return self._index

    def name(self) -> str:
        return self._name

    def solution_value(self) -> float:
        return self._solver._solution_value(self._index)

    def __hash__(self) -> int:
        return id(self)

    def __repr__(self) -> str:
        return f"Variable({self._name})"


class LinearConstraint:
    """``lower_bound <= expression <= upper_bound``, constant folded in."""

    __slots__ = ("expression", "lower_bound", "upper_bound")

    def __init__(self, expression: LinearExpr, lower_bound: float, upper_bound: float) -> None:
        # `expression` still carries its constant; move it to the bounds so the
        # proto holds only variable terms, which is what MPSolver expects.
        self.expression = LinearExpr(expression.terms)
        offset = expression.constant
        self.lower_bound = lower_bound if lower_bound <= -INFINITY else lower_bound - offset
        self.upper_bound = upper_bound if upper_bound >= INFINITY else upper_bound - offset

    def __bool__(self) -> bool:
        raise TypeError("a pywraplp constraint has no truth value; pass it to Solver.Add")


class Solver:
    """A MILP, solved by SCIP inside ``or-tools-wasm``."""

    OPTIMAL = 0
    FEASIBLE = 1
    INFEASIBLE = 2
    UNBOUNDED = 3
    ABNORMAL = 4
    MODEL_INVALID = 5
    NOT_SOLVED = 6

    def __init__(self, name: str, solver_type: int) -> None:
        self._solver_type = solver_type
        self._model = pb.MPModelProto()
        self._model.name = name
        self._variable_count = 0
        self._time_limit_ms: int | None = None
        self._response: pb.MPSolutionResponse | None = None

    @staticmethod
    def CreateSolver(name: str) -> Solver | None:  # noqa: N802 - upstream's name
        solver_type = _SOLVER_TYPES.get(name.upper())
        if solver_type is None:
            return None
        return Solver(name, solver_type)

    def infinity(self) -> float:
        return INFINITY

    def SetTimeLimit(self, milliseconds: int) -> None:  # noqa: N802
        self._time_limit_ms = int(milliseconds)

    def NumVar(self, lb: float, ub: float, name: str) -> Variable:  # noqa: N802
        return self._new_variable(lb, ub, name, integer=False)

    def IntVar(self, lb: float, ub: float, name: str) -> Variable:  # noqa: N802
        return self._new_variable(lb, ub, name, integer=True)

    def BoolVar(self, name: str) -> Variable:  # noqa: N802
        return self._new_variable(0, 1, name, integer=True)

    def _new_variable(self, lb: float, ub: float, name: str, *, integer: bool) -> Variable:
        proto = self._model.variable.add()
        proto.lower_bound = float(lb)
        proto.upper_bound = float(ub)
        proto.is_integer = integer
        proto.name = name
        variable = Variable(self, self._variable_count, name)
        self._variable_count += 1
        return variable

    def Add(self, constraint: LinearConstraint, name: str = "") -> LinearConstraint:  # noqa: N802
        if not isinstance(constraint, LinearConstraint):
            raise TypeError(
                "Solver.Add takes a comparison of linear expressions, "
                f"not {type(constraint).__name__}"
            )
        proto = self._model.constraint.add()
        # Real pywraplp auto-names an unnamed constraint; matching it keeps the
        # two models byte-comparable in the differential test.
        proto.name = name or f"auto_c_{len(self._model.constraint) - 1:09d}"
        proto.is_lazy = False
        proto.lower_bound = constraint.lower_bound
        proto.upper_bound = constraint.upper_bound
        for index, coefficient in sorted(constraint.expression.terms.items()):
            if coefficient == 0.0:
                continue
            proto.var_index.append(index)
            proto.coefficient.append(coefficient)
        return constraint

    @staticmethod
    def Sum(expressions: Iterable[LinearExpr | float]) -> LinearExpr:  # noqa: N802
        total = LinearExpr()
        for expression in expressions:
            total = total + expression
        return total

    def Minimize(self, expression: LinearExpr | float) -> None:  # noqa: N802
        self._set_objective(expression, maximize=False)

    def Maximize(self, expression: LinearExpr | float) -> None:  # noqa: N802
        self._set_objective(expression, maximize=True)

    def _set_objective(self, expression: LinearExpr | float, *, maximize: bool) -> None:
        expr = LinearExpr._coerce(expression)
        for variable in self._model.variable:
            # Cleared, not zeroed: the field has explicit presence, and a
            # present 0.0 is a different proto from an absent one.
            variable.ClearField("objective_coefficient")
        for index, coefficient in expr.terms.items():
            if coefficient:
                self._model.variable[index].objective_coefficient = coefficient
        self._model.objective_offset = expr.constant
        self._model.maximize = maximize

    def Solve(self) -> int:  # noqa: N802
        request = pb.MPModelRequest()
        request.solver_type = self._solver_type
        if self._time_limit_ms is not None:
            request.solver_time_limit_seconds = self._time_limit_ms / 1000.0
        request.model.CopyFrom(self._model)
        raw = _wasm_bridge.call("mp_solve", request.SerializeToString())
        response = pb.MPSolutionResponse()
        response.ParseFromString(raw)
        self._response = response
        # MPSolverResponseStatus and pywraplp's ResultStatus share their
        # numbering, so the enum value passes through unchanged.
        return int(response.status)

    def Objective(self) -> _Objective:  # noqa: N802
        return _Objective(self)

    def objective_value(self) -> float:
        return self._checked_response().objective_value

    def NumVariables(self) -> int:  # noqa: N802
        return len(self._model.variable)

    def NumConstraints(self) -> int:  # noqa: N802
        return len(self._model.constraint)

    def ExportModelAsLpFormat(self, obfuscated: bool = False) -> str:  # noqa: N802
        raise NotImplementedError("LP-format export lives in libortools, with no wasm entry point")

    def model_proto(self) -> pb.MPModelProto:
        """The model as built.  Used by the differential tests, not by flab2bp."""
        return self._model

    def _checked_response(self) -> pb.MPSolutionResponse:
        if self._response is None:
            raise RuntimeError("Solve() has not been called yet")
        return self._response

    def _solution_value(self, index: int) -> float:
        response = self._checked_response()
        if index >= len(response.variable_value):
            raise RuntimeError(
                "the solver returned no value for this variable; its status was "
                f"{pb.MPSolverResponseStatus.Name(response.status)}"
            )
        return response.variable_value[index]


class _Objective:
    __slots__ = ("_solver",)

    def __init__(self, solver: Solver) -> None:
        self._solver = solver

    def Value(self) -> float:  # noqa: N802
        return self._solver.objective_value()
