"""A multi-cell bucket grid, built once per previews value and shared by both
belt-collision rules that query it.

`belt_collisions` and `stable_belt_collisions` (`dsp/colliders.py`) both call
`_belt_overlap_candidates`, which used to rebuild its spatial index --
`grid: dict[tuple[int, int], list[int]]` -- from scratch on every call.
`layout/validate.py` reaches both, from `game.belt_crossing` and
`game.belt_collide`, in one validation pass over one `Context`.

The validator shares one immutable preview tuple within each ``Context``.
Other callers and later validation calls can supply distinct value-equal
tuples, so this cache remains keyed by value rather than object identity.
``Preview`` is ``@dataclass(frozen=True)`` and therefore hashable. A
caller that hands an unhashable sequence (a plain `list`, which existing
tests in `tests/dsp/test_colliders.py` do use directly against
`_belt_overlap_candidates`) still works correctly -- it is simply never
cached, exactly as if this module did not exist for that call.

Backend: a plain dict bucket grid, matching the real
`_belt_overlap_candidates` exactly -- cell size `8.0`, one item registered at
every cell its reach-expanded box occupies, looked up by ONE probe-derived
key with no neighbour expansion (registration already over-covers by `reach`).
Flat geometry uses world XZ cells; projected geometry uses world XYZ cells
and the full box circumradius plus `BELT_PROBE_RADIUS`.
`littletable` adds nothing to a bucket grid and `polars` cannot express one.

This module is deliberately geometry-agnostic: it knows cells and item
indices, never `Box`, `Preview` or `sphere_box_overlap`. The box-reach
registration math and the final `sphere_box_overlap` filtering both stay in
`dsp/colliders.py`, which hands this module pre-computed per-item cell lists.
That keeps the dependency one-directional -- `dsp/colliders.py` imports
`BeltOverlap` from here, never the reverse -- the same shape as every other
module in this package.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Sequence
from typing import Any

Cell = tuple[int, int] | tuple[int, int, int]


class BeltOverlap:
    """Which registered item indices share a grid cell with a probe key."""

    __slots__ = ("_grid",)

    #: Bounded to the two most recent ``previews`` values, matching the pass
    #: structure this exists for: one validation pass, two rules asking.
    _cache: dict[Hashable, BeltOverlap] = {}

    def __init__(self, grid: dict[Cell, list[int]]) -> None:
        self._grid = {cell: tuple(dict.fromkeys(indices)) for cell, indices in grid.items()}

    @staticmethod
    def of(cells_by_index: Sequence[Iterable[Cell]]) -> BeltOverlap:
        """Index item ``i`` at every cell in ``cells_by_index[i]``.

        An item may repeat within its own cell list when several of its boxes
        register the same cell. Finalize each bucket once, preserving the
        first-registered order for every subsequent probe.
        """
        grid: dict[Cell, list[int]] = {}
        for index, cells in enumerate(cells_by_index):
            for cell in cells:
                grid.setdefault(cell, []).append(index)
        return BeltOverlap(grid)

    @classmethod
    def for_previews(
        cls,
        previews: Any,
        cells_of: Callable[[Any], Sequence[Iterable[Cell]]],
    ) -> BeltOverlap:
        """The index for one ``previews`` value, built at most once per value.

        Keyed on ``previews`` itself, not its identity -- see the module
        docstring for why. A ``previews`` that is not hashable (a plain
        ``list``) is indexed normally but never cached.
        """
        try:
            hit = cls._cache.get(previews)
        except TypeError:
            return cls.of(cells_of(previews))
        if hit is not None:
            return hit
        index = cls.of(cells_of(previews))
        if len(cls._cache) >= 2:
            cls._cache.pop(next(iter(cls._cache)))
        cls._cache[previews] = index
        return index

    @classmethod
    def clear_cache(cls) -> None:
        """Drop every memoized index. Tests only."""
        cls._cache.clear()

    def candidates(self, key: Cell) -> tuple[int, ...]:
        """Unique item indices in this cell, in first-registered order."""
        return self._grid.get(key, ())
