"""Pure-Python stand-in for ortools 9.11's ``cp_model_helper`` pybind module.

``cp_model.py`` is vendored verbatim from the 9.11 wheel.  Almost all of it is
proto-building, but it calls out to this module for eight numeric predicates
that upstream implements in C++ purely for speed.  There is no algorithm here
to get subtly wrong -- each one is a range check or an equality test -- and
``tests/web/test_pyshim_helpers.py`` pins every one of them against the real
pybind module, so a divergence is a test failure rather than a wrong blueprint.

The one that carries any weight is ``capped_subtraction``: CP-SAT uses int64
saturation, not Python's unbounded integers, and a domain bound that silently
grows past ``kint64max`` is a model the solver rejects.
"""

from __future__ import annotations

import numbers
from typing import Any

import numpy as np

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1
INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1

__all__ = [
    "INT32_MAX",
    "INT32_MIN",
    "INT_MAX",
    "INT_MIN",
    "assert_is_a_number",
    "assert_is_boolean",
    "assert_is_int32",
    "assert_is_int64",
    "assert_is_zero_or_one",
    "capped_subtraction",
    "is_boolean",
    "is_integral",
    "is_minus_one",
    "is_one",
    "is_zero",
]


def is_boolean(x: Any) -> bool:
    """``True`` for a Python or numpy bool, and for nothing else.

    ``isinstance(True, int)`` is also true, so callers that want to branch on
    "is this literally a boolean" cannot use ``isinstance(x, int)``.
    """
    return isinstance(x, (bool, np.bool_))


def is_integral(x: Any) -> bool:
    """``True`` for anything that is exactly an integer, float included."""
    if isinstance(x, (int, np.integer)):
        return True
    if isinstance(x, (float, np.floating)):
        return float(x).is_integer()
    return isinstance(x, numbers.Integral)


def is_zero(x: Any) -> bool:
    return isinstance(x, numbers.Number) and not is_boolean(x) and x == 0


def is_one(x: Any) -> bool:
    return isinstance(x, numbers.Number) and not is_boolean(x) and x == 1


def is_minus_one(x: Any) -> bool:
    return isinstance(x, numbers.Number) and not is_boolean(x) and x == -1


def assert_is_a_number(x: Any) -> int | float:
    """Return ``x`` as a Python number, or say what it was instead."""
    if isinstance(x, (int, np.integer)) and not is_boolean(x):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x)
    if is_boolean(x):
        return int(x)
    raise TypeError(f"Not a number: {x!r}")


def _as_integer(x: Any) -> int:
    if is_boolean(x):
        return int(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        value = float(x)
        if not value.is_integer():
            raise TypeError(f"Not an integer: {x!r}")
        return int(value)
    raise TypeError(f"Not an integer: {x!r}")


def assert_is_int64(x: Any) -> int:
    value = _as_integer(x)
    if value < INT_MIN or value > INT_MAX:
        raise OverflowError(f"Does not fit in an int64: {x!r}")
    return value


def assert_is_int32(x: Any) -> int:
    value = _as_integer(x)
    if value < INT32_MIN or value > INT32_MAX:
        raise OverflowError(f"Does not fit in an int32: {x!r}")
    return value


def assert_is_zero_or_one(x: Any) -> int:
    value = _as_integer(x)
    if value not in (0, 1):
        raise TypeError(f"Not 0 or 1: {x!r}")
    return value


def assert_is_boolean(x: Any) -> bool:
    if not is_boolean(x):
        raise TypeError(f"Not a boolean: {x!r}")
    return bool(x)


def capped_subtraction(x: int, y: int) -> int:
    """``x - y`` in int64 saturating arithmetic, exactly as CP-SAT does it.

    Python integers do not overflow, so a naive ``x - y`` on a domain bound of
    ``kint64min`` produces a value the solver's proto cannot hold.  Upstream
    saturates; so do we.
    """
    x = assert_is_int64(x)
    y = assert_is_int64(y)
    if y == 0:
        return x
    if x == y:
        if x == INT_MAX or x == INT_MIN:
            raise OverflowError("Integer NaN: subtracting infinities of the same sign")
        return 0
    if x == INT_MAX or x == INT_MIN:
        return x
    if y == INT_MAX:
        return INT_MIN
    if y == INT_MIN:
        return INT_MAX
    return max(INT_MIN, min(INT_MAX, x - y))
