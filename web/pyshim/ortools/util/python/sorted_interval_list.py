"""Pure-Python stand-in for ortools' ``sorted_interval_list.Domain``.

``Domain`` is a union of disjoint closed int64 intervals kept sorted and
merged.  ortools implements it in C++; ``cp_model.py`` uses it for exactly one
thing that matters here -- turning ``lb <= expr <= ub`` into the flat
``[lb, ub, ...]`` list a ``LinearConstraintProto`` carries -- but it is a real
set type and getting the normalisation wrong would silently widen or narrow a
constraint.  So it is a real set type here too: construction merges and sorts,
and ``tests/clientside/test_ortools_shim.py`` pins the result against the C++
one over a spread of overlapping, touching and disjoint inputs.

Bounds saturate at int64 rather than growing, matching the C++ type.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

INT_MIN = -(2**63)
INT_MAX = 2**63 - 1

__all__ = ["Domain"]


def _clamp(value: int) -> int:
    return max(INT_MIN, min(INT_MAX, int(value)))


def _normalise(intervals: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Sort, drop empties, and merge anything overlapping or adjacent."""
    ordered = sorted((lo, hi) for lo, hi in intervals if lo <= hi)
    merged: list[list[int]] = []
    for lo, hi in ordered:
        # `hi + 1` because [1, 2] and [3, 4] are one interval over integers.
        if merged and lo <= merged[-1][1] + 1 and merged[-1][1] != INT_MAX:
            merged[-1][1] = max(merged[-1][1], hi)
        elif merged and merged[-1][1] == INT_MAX:
            continue
        else:
            merged.append([lo, hi])
    return tuple((lo, hi) for lo, hi in merged)


class Domain:
    """A sorted, merged union of closed int64 intervals."""

    __slots__ = ("_intervals",)

    def __init__(self, left: int = 0, right: int = -1) -> None:
        self._intervals = _normalise([(_clamp(left), _clamp(right))])

    # -- constructors -------------------------------------------------------

    @classmethod
    def _of(cls, intervals: Iterable[tuple[int, int]]) -> Domain:
        obj = cls.__new__(cls)
        obj._intervals = _normalise((_clamp(lo), _clamp(hi)) for lo, hi in intervals)
        return obj

    @classmethod
    def all_values(cls) -> Domain:
        return cls._of([(INT_MIN, INT_MAX)])

    @classmethod
    def from_values(cls, values: Iterable[int]) -> Domain:
        return cls._of([(int(v), int(v)) for v in values])

    @classmethod
    def from_intervals(cls, intervals: Iterable[Sequence[int]]) -> Domain:
        return cls._of([(int(pair[0]), int(pair[1])) for pair in intervals])

    @classmethod
    def from_flat_intervals(cls, flat: Sequence[int]) -> Domain:
        if len(flat) % 2:
            raise ValueError("a flat interval list must have an even length")
        return cls._of([(int(flat[i]), int(flat[i + 1])) for i in range(0, len(flat), 2)])

    # -- accessors ----------------------------------------------------------

    def flattened_intervals(self) -> list[int]:
        out: list[int] = []
        for lo, hi in self._intervals:
            out.append(lo)
            out.append(hi)
        return out

    def intervals(self) -> list[list[int]]:
        return [[lo, hi] for lo, hi in self._intervals]

    def is_empty(self) -> bool:
        return not self._intervals

    def size(self) -> int:
        return sum(hi - lo + 1 for lo, hi in self._intervals)

    def min(self) -> int:
        if not self._intervals:
            raise ValueError("an empty domain has no minimum")
        return self._intervals[0][0]

    def max(self) -> int:
        if not self._intervals:
            raise ValueError("an empty domain has no maximum")
        return self._intervals[-1][1]

    def contains(self, value: int) -> bool:
        value = int(value)
        return any(lo <= value <= hi for lo, hi in self._intervals)

    # -- set algebra --------------------------------------------------------

    def complement(self) -> Domain:
        out: list[tuple[int, int]] = []
        cursor = INT_MIN
        for lo, hi in self._intervals:
            if cursor < lo:
                out.append((cursor, lo - 1))
            if hi == INT_MAX:
                return Domain._of(out)
            cursor = hi + 1
        out.append((cursor, INT_MAX))
        return Domain._of(out)

    def negation(self) -> Domain:
        return Domain._of([(-hi, -lo) for lo, hi in self._intervals])

    def union_with(self, other: Domain) -> Domain:
        return Domain._of([*self._intervals, *other._intervals])

    def intersection_with(self, other: Domain) -> Domain:
        out: list[tuple[int, int]] = []
        for lo, hi in self._intervals:
            for other_lo, other_hi in other._intervals:
                low, high = max(lo, other_lo), min(hi, other_hi)
                if low <= high:
                    out.append((low, high))
        return Domain._of(out)

    # -- protocol -----------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Domain):
            return NotImplemented
        return self._intervals == other._intervals

    def __hash__(self) -> int:
        return hash(self._intervals)

    def __str__(self) -> str:
        if not self._intervals:
            return "[]"
        parts = [str(lo) if lo == hi else f"{lo},{hi}" for lo, hi in self._intervals]
        return "[" + "][".join(parts) + "]"

    def __repr__(self) -> str:
        return f"Domain({self})"
