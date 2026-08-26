"""The browser build swaps ortools out.  These tests say it swapped like-for-like.

``web/pyshim`` replaces ``ortools`` inside Pyodide: ortools 9.11's own
pure-Python ``cp_model.py`` verbatim, plus pure-Python versions of the three
things upstream implements in C++.  The risk that matters is not "it crashes"
-- it is "it builds a slightly different model and ships a slightly different
factory".  So the assertions here are on the *model*, not on the API:

* the CP-SAT model the shim builds, for every constraint kind flab2bp uses, is
  the same ``CpModelProto`` the installed ortools builds from the same calls;
* the MILP model the shim builds, for the shape ``rates.solve`` builds, is the
  same ``MPModelProto`` real ``pywraplp`` builds;
* ``Domain`` normalises exactly as the C++ one does.

The shim shadows ``ortools``, so every use of it happens in a subprocess.
Nothing here needs a browser, a wasm build, or a network.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Neither protobuf nor ortools ships type information, matching how the rest
# of this project imports them.
from google.protobuf import text_format  # type: ignore[import-untyped]
from ortools.linear_solver import linear_solver_pb2  # type: ignore[import-untyped]
from ortools.linear_solver import pywraplp as native_pywraplp
from ortools.sat import cp_model_pb2
from ortools.sat.python import cp_model as native_cp_model
from ortools.util.python import (
    sorted_interval_list as native_domain,  # type: ignore[import-untyped]
)

from tests.clientside import _shim_child

CHILD = Path(_shim_child.__file__)
SHIM = Path(__file__).resolve().parents[2] / "web" / "pyshim"

pytestmark = pytest.mark.skipif(
    not (SHIM / "ortools" / "sat" / "python" / "cp_model.py").exists(),
    reason="web/pyshim is not present; run web/build_payload.py first",
)


def _child(request: str) -> str:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(CHILD), request],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    if result.returncode:
        pytest.fail(f"the shim child failed on {request!r}:\n{result.stderr}")
    return result.stdout.strip()


def _sorted_terms(expression: object) -> None:
    """Sort a linear expression's (var, coeff) pairs in place.

    A linear expression is a *set* of terms, and 9.11 and 9.15 accumulate them
    in different orders.  Sorting is the only normalisation applied anywhere in
    this file, and it cannot hide a difference in which terms exist or what
    their coefficients are.
    """
    pairs = sorted(zip(expression.vars, expression.coeffs, strict=True))  # type: ignore[attr-defined]
    del expression.vars[:]  # type: ignore[attr-defined]
    del expression.coeffs[:]  # type: ignore[attr-defined]
    expression.vars.extend(v for v, _ in pairs)  # type: ignore[attr-defined]
    expression.coeffs.extend(c for _, c in pairs)  # type: ignore[attr-defined]


def _normalised(model: cp_model_pb2.CpModelProto) -> cp_model_pb2.CpModelProto:
    out = cp_model_pb2.CpModelProto()
    out.CopyFrom(model)
    for constraint in out.constraints:
        kind = constraint.WhichOneof("constraint")
        if kind == "linear":
            _sorted_terms(constraint.linear)
        elif kind in ("lin_max", "int_prod", "int_div", "int_mod"):
            argument = getattr(constraint, kind)
            _sorted_terms(argument.target)
            for expression in argument.exprs:
                _sorted_terms(expression)
        elif kind == "table":
            # 9.11 writes a table's columns as `vars`; 9.15 writes them as
            # single-term `exprs`. Both fields are in the proto and CP-SAT
            # reads both, so rewrite 9.15's form into 9.11's to compare.
            table = constraint.table
            if table.exprs and not table.vars:
                for expression in table.exprs:
                    assert list(expression.coeffs) == [1] and not expression.offset
                    table.vars.append(expression.vars[0])
                del table.exprs[:]
    if out.HasField("objective"):
        _sorted_terms(out.objective)
    return out


def test_the_shim_builds_the_same_cp_sat_model_as_the_installed_ortools() -> None:
    from_shim = cp_model_pb2.CpModelProto()
    from_shim.ParseFromString(base64.b64decode(_child("cp_sat")))

    native = _shim_child._build_cp_sat(native_cp_model)
    from_native = text_format.Parse(str(native.proto), cp_model_pb2.CpModelProto())

    assert len(from_shim.variables) == len(from_native.variables)
    assert len(from_shim.constraints) == len(from_native.constraints)
    assert text_format.MessageToString(_normalised(from_shim)) == text_format.MessageToString(
        _normalised(from_native)
    )


def test_the_only_representational_difference_is_the_table_constraint() -> None:
    """Pin the one place 9.11 and 9.15 disagree, so it cannot grow unnoticed.

    ``add_allowed_assignments`` is written as ``TableConstraintProto.vars`` by
    9.11 and as single-term ``exprs`` by 9.15.  Normalising it away above is
    only safe because the difference is exactly this and nothing else; if
    another field ever diverges, this test is where it shows up.
    """
    from_shim = cp_model_pb2.CpModelProto()
    from_shim.ParseFromString(base64.b64decode(_child("cp_sat")))
    native = _shim_child._build_cp_sat(native_cp_model)
    from_native = text_format.Parse(str(native.proto), cp_model_pb2.CpModelProto())

    shim_tables = [c.table for c in from_shim.constraints if c.WhichOneof("constraint") == "table"]
    native_tables = [
        c.table for c in from_native.constraints if c.WhichOneof("constraint") == "table"
    ]
    assert len(shim_tables) == len(native_tables) == 1
    assert list(shim_tables[0].vars) and not shim_tables[0].exprs
    assert list(native_tables[0].exprs) and not native_tables[0].vars
    assert list(shim_tables[0].values) == list(native_tables[0].values)


def test_the_shim_builds_the_same_milp_as_real_pywraplp() -> None:
    from_shim = linear_solver_pb2.MPModelProto()
    from_shim.ParseFromString(base64.b64decode(_child("mp")))

    solver = _shim_child._build_mp(native_pywraplp)
    from_native = linear_solver_pb2.MPModelProto()
    solver.ExportModelToProto(from_native)

    # Real pywraplp names the model after the backend; the shim does too, but
    # the name is not part of the program.
    from_shim.ClearField("name")
    from_native.ClearField("name")
    assert text_format.MessageToString(from_shim) == text_format.MessageToString(from_native)


def test_the_shim_domain_normalises_exactly_as_the_c_plus_plus_one_does() -> None:
    got = json.loads(_child("helpers"))["domains"]
    Domain = native_domain.Domain

    merged = Domain.from_intervals([[1, 2], [3, 4], [9, 9]])
    assert got["merge_adjacent"] == merged.flattened_intervals()
    assert got["overlap"] == Domain.from_intervals([[1, 6], [3, 4]]).flattened_intervals()
    assert got["unsorted"] == Domain.from_intervals([[9, 9], [1, 2]]).flattened_intervals()
    assert got["flat"] == Domain.from_flat_intervals([1, 2, 3, 4]).flattened_intervals()
    assert got["complement"] == Domain(0, 5).complement().flattened_intervals()
    negated = Domain.from_intervals([[1, 3], [7, 9]]).negation()
    assert got["negation"] == negated.flattened_intervals()
    assert got["values"] == Domain.from_values([5, 1, 2, 9]).flattened_intervals()
    assert (
        got["intersect"]
        == Domain.from_intervals([[0, 10]])
        .intersection_with(Domain.from_intervals([[5, 20]]))
        .flattened_intervals()
    )
    assert got["str"] == str(Domain.from_intervals([[1, 2], [5, 9]]))
    assert got["size"] == Domain.from_intervals([[1, 3], [10, 11]]).size()
    assert got["contains"] == [Domain(2, 4).contains(v) for v in (1, 2, 3, 4, 5)]


def test_the_numeric_helpers_saturate_at_int64_the_way_cp_sat_does() -> None:
    # No installed counterpart to diff against -- ortools 9.15 dropped these
    # from its Python surface -- so these are the semantics CP-SAT's C++
    # `CapSub` defines, pinned by hand.
    got = json.loads(_child("helpers"))["numeric"]
    int_min, int_max = -(2**63), 2**63 - 1
    assert got["capped"] == [2, int_min, int_max, int_max, 7]
    assert got["is_zero"] == [True, True, False, False]
    assert got["is_one"] == [True, True, False, False]
    assert got["is_minus_one"] == [True, True, False]
    assert got["is_boolean"] == [True, False, False]
    assert got["assert_is_int64"] == [3, 3]
