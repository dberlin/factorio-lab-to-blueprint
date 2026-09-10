"""A multi-cell bucket grid, built once per previews value and shared by both
belt-collision rules that query it.

`belt_collisions` and `stable_belt_collisions` (`dsp/colliders.py`) both call
`_belt_overlap_candidates`, which used to rebuild its spatial index --
`grid: dict[tuple[int, int], list[int]]` -- from scratch on every call.
`layout/validate.py` reaches both, from `game.belt_crossing` and
`game.belt_collide`, in one validation pass over one `Context`.

Deviation from this task's brief and from controller ruling P-8's own
suggested fallback, found while implementing against the real source (ruling
P-2): both assumed the two rules are handed the SAME ``previews`` object, and
that memoizing on `id(previews)` therefore dedupes the rebuild. They are not.
`validate.py:_belt_collide_findings` calls `_paste_previews(ctx)` -- a plain,
unmemoized function -- independently for each of the two checks, so it builds
a NEW `tuple[Preview, ...]` every time, even within one validation pass over
one `ctx`. `id()`-keyed caching would never hit in production.

`Preview` is `@dataclass(frozen=True)` and therefore hashable, and equal
`ctx.placement.buildings` input produces value-equal (if not identical)
`Preview` tuples across the two calls. This module keys its cache on the
VALUE of ``previews`` instead of its identity, which is what actually
achieves the dedup `_belt_collide_findings`'s real call pattern needs. A
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
        self._grid = grid

    @staticmethod
    def of(cells_by_index: Sequence[Iterable[Cell]]) -> BeltOverlap:
        """Index item ``i`` at every cell in ``cells_by_index[i]``.

        An item may repeat within its own cell list (two boxes belonging to
        the same preview registering the same cell); duplicates are kept in
        the grid here and removed by :meth:`candidates`, matching
        ``dict.fromkeys(grid.get(key, ()))`` in the real source exactly.
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
        """Item indices registered at this ONE cell, duplicates removed, in
        first-registered order -- ``dict.fromkeys(grid.get(key, ()))``."""
        return tuple(dict.fromkeys(self._grid.get(key, ())))
