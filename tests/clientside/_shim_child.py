"""Build models through ``web/pyshim`` and print them, in a fresh process.

The shim deliberately shadows ``ortools``.  Importing it into the pytest
process would replace the real library for every other test, so every use of
it happens out here, behind a subprocess boundary, and only serialized protos
cross back.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

SHIM = Path(__file__).resolve().parents[2] / "web" / "pyshim"


def _install_shim() -> None:
    sys.path.insert(0, str(SHIM))
    for name in [m for m in sys.modules if m == "ortools" or m.startswith("ortools.")]:
        del sys.modules[name]


def cp_sat_model() -> str:
    from ortools.sat.python import cp_model

    assert str(SHIM) in cp_model.__file__, cp_model.__file__
    model = _build_cp_sat(cp_model)
    return base64.b64encode(model.proto.SerializeToString()).decode()


def mp_model() -> str:
    from ortools.linear_solver import pywraplp

    assert str(SHIM) in pywraplp.__file__, pywraplp.__file__
    solver = _build_mp(pywraplp)
    return base64.b64encode(solver.model_proto().SerializeToString()).decode()


def helpers() -> dict[str, object]:
    from ortools.sat.python import cp_model_helper as cmh
    from ortools.util.python import sorted_interval_list as sil

    domains = {
        "merge_adjacent": sil.Domain.from_intervals([[1, 2], [3, 4], [9, 9]]).flattened_intervals(),
        "overlap": sil.Domain.from_intervals([[1, 6], [3, 4]]).flattened_intervals(),
        "unsorted": sil.Domain.from_intervals([[9, 9], [1, 2]]).flattened_intervals(),
        "flat": sil.Domain.from_flat_intervals([1, 2, 3, 4]).flattened_intervals(),
        "complement": sil.Domain(0, 5).complement().flattened_intervals(),
        "negation": sil.Domain.from_intervals([[1, 3], [7, 9]]).negation().flattened_intervals(),
        "values": sil.Domain.from_values([5, 1, 2, 9]).flattened_intervals(),
        "intersect": sil.Domain.from_intervals([[0, 10]])
        .intersection_with(sil.Domain.from_intervals([[5, 20]]))
        .flattened_intervals(),
        "str": str(sil.Domain.from_intervals([[1, 2], [5, 9]])),
        "size": sil.Domain.from_intervals([[1, 3], [10, 11]]).size(),
        "contains": [sil.Domain(2, 4).contains(v) for v in (1, 2, 3, 4, 5)],
    }
    numeric = {
        "capped": [
            cmh.capped_subtraction(5, 3),
            cmh.capped_subtraction(cmh.INT_MIN, 1),
            cmh.capped_subtraction(cmh.INT_MAX, -1),
            cmh.capped_subtraction(0, cmh.INT_MIN),
            cmh.capped_subtraction(7, 0),
        ],
        "is_zero": [cmh.is_zero(0), cmh.is_zero(0.0), cmh.is_zero(1), cmh.is_zero(False)],
        "is_one": [cmh.is_one(1), cmh.is_one(1.0), cmh.is_one(True), cmh.is_one(2)],
        "is_minus_one": [cmh.is_minus_one(-1), cmh.is_minus_one(-1.0), cmh.is_minus_one(1)],
        "is_boolean": [cmh.is_boolean(True), cmh.is_boolean(1), cmh.is_boolean(0.0)],
        "assert_is_int64": [cmh.assert_is_int64(3), cmh.assert_is_int64(3.0)],
    }
    return {"domains": domains, "numeric": numeric}


def _build_cp_sat(cp_model):  # noqa: ANN001, ANN202 - one module, two versions
    """The constraint kinds flab2bp actually uses, in one model."""
    model = cp_model.CpModel()
    xs = [model.new_int_var(0, 40, f"x{i}") for i in range(4)]
    ys = [model.new_int_var(0, 40, f"y{i}") for i in range(4)]
    bs = [model.new_bool_var(f"b{i}") for i in range(4)]

    model.add(xs[0] + 2 * xs[1] <= 30)
    model.add(xs[2] - xs[3] >= -5)
    model.add(sum(bs) == 2)
    model.add_exactly_one(bs)
    model.add_bool_or([bs[0], bs[1].negated()])
    model.add_bool_and([bs[2], bs[3]]).only_enforce_if(bs[0])
    model.add(xs[0] == xs[1]).only_enforce_if(bs[1])

    span = model.new_int_var(0, 80, "span")
    model.add_max_equality(span, xs)
    gap = model.new_int_var(0, 80, "gap")
    model.add_abs_equality(gap, xs[0] - xs[1])

    x_intervals = [model.new_fixed_size_interval_var(xs[i], 3, f"xi{i}") for i in range(4)]
    y_intervals = [model.new_fixed_size_interval_var(ys[i], 2, f"yi{i}") for i in range(4)]
    model.add_no_overlap_2d(x_intervals, y_intervals)

    model.add_allowed_assignments([xs[0], ys[0]], [(0, 0), (3, 4), (6, 8)])
    for i in range(4):
        model.add_hint(xs[i], i * 3)
    model.minimize(span + gap + 2 * sum(ys))
    return model


def _build_mp(pywraplp):  # noqa: ANN001, ANN202
    """The shape ``flab2bp.rates.solve`` builds: rates, counts, balances."""
    solver = pywraplp.Solver.CreateSolver("SCIP")
    assert solver is not None
    crafts = [solver.NumVar(0.0, solver.infinity(), f"x{i}") for i in range(3)]
    machines = [solver.IntVar(0, 100000, f"n{i}") for i in range(3)]
    flags = [solver.IntVar(0, 1, f"m{i}") for i in range(3)]

    for craft, machine, rate in zip(crafts, machines, (0.75, 1.5, 0.25), strict=True):
        solver.Add(craft - rate * machine <= 0)
    for flag, machine in zip(flags, machines, strict=True):
        solver.Add(machine - 100000 * flag <= 0)
    solver.Add(solver.Sum(flags) <= 1)

    expr = None
    for craft, net in zip(crafts, (2.0, -1.0, 0.5), strict=True):
        term = net * craft
        expr = term if expr is None else expr + term
    solver.Add(expr >= 12.5)
    solver.Add(crafts[0] + crafts[1] - 3.0 * crafts[2] >= 1.0)
    areas = (9.0, 16.0, 4.0)
    solver.Minimize(solver.Sum(a * m for m, a in zip(machines, areas, strict=True)))
    return solver


if __name__ == "__main__":
    _install_shim()
    what = sys.argv[1]
    if what == "cp_sat":
        print(cp_sat_model())
    elif what == "mp":
        print(mp_model())
    elif what == "helpers":
        print(json.dumps(helpers()))
    else:  # pragma: no cover
        raise SystemExit(f"unknown request {what!r}")
