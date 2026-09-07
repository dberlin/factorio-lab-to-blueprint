"""Sorters, indexed by what they draw from, feed, and carry.

Four separate places rebuild this same map ad hoc from `ctx.of_kind(SORTER)`
(real source read at HEAD, `layout/validate.py`): `_belt_reaches_any`'s
inline filter (~4608-4627, run once per BFS step), `_unsprayed_belts`'s
`hops` (~4977-4988), `_sprayed_cargo_reaches_machines`'s `feeds`
(~5048-5057), and the flow-rate loop inside `_lane_balance` (~5314-5340).
`ctx.cache.sorter_items` / `_sorter_items` (~5860) resolves the third key,
the item each sorter carries, once per `Context` -- this type takes that
resolved value as input rather than recomputing it, so it stays free of
`validate` (importing it would be a cycle).

Backend: littletable. The collection is frozen (`Context.of_kind` is a
memoized tuple on a frozen `Context`) but it is queried on THREE keys --
`input_obj`, `output_obj`, and the resolved item -- by at least four
consumers. Hand-kept dicts, one per consumer, is the duplication being
removed; one table with three indexes is one backend for one collection.

Rows are wrapped in `_SorterRecord` rather than inserted directly:
littletable rebinds attributes on the objects it holds and `PlacedBuilding`
is `@dataclass(frozen=True, slots=True)`, which cannot take one.

ORDER IS PART OF THE CONTRACT. `Context.of_kind` always hands its rows to
`Sorters.of` already in placement order (ascending building index), and
callers extend a BFS frontier with these results, so every accessor returns
that same order. littletable's `by.field[value]` was checked directly and
returns records in TABLE INSERTION order, not any order derived from a key's
value -- so accessors resort explicitly by each row's position in the
`rows` `Sorters.of` was given, rather than trusting that coincidence to
hold across littletable versions.

Ruling I-7 / the `Buildings` question: a sibling branch may later land a
`Buildings` type covering `Placement.buildings`, at which point
`input_obj`/`output_obj` resolution here could delegate to it. That type
does not exist on this branch. The two link accessors below (`drawing_from`,
`feeding`) are kept thin and self-contained so that delegation, when it
lands, is a small edit rather than a rewrite.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import littletable

from flab2bp.indexed._record import IndexRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flab2bp.layout.base import PlacedBuilding


@dataclass
class _SorterRecord(IndexRecord):
    index: int = -1
    input_obj: int | None = None
    output_obj: int | None = None
    item: str | None = None


class Sorters:
    """One placement's sorters, answered by key instead of by scan."""

    def __init__(self, rows: Iterable[tuple[int, PlacedBuilding, str | None]]) -> None:
        table: littletable.Table = littletable.Table("sorters")
        table.create_index("input_obj")
        table.create_index("output_obj")
        table.create_index("item")
        order: list[int] = []
        payloads: dict[int, PlacedBuilding] = {}
        items: dict[int, str | None] = {}
        for index, building, item in rows:
            table.insert(
                _SorterRecord(
                    payload=building,
                    index=index,
                    input_obj=building.input_obj,
                    output_obj=building.output_obj,
                    item=item,
                )
            )
            order.append(index)
            payloads[index] = building
            items[index] = item
        self._table = table
        self._order = tuple(order)
        self._payloads = payloads
        self._items = items
        self._rank = {index: rank for rank, index in enumerate(order)}

    @classmethod
    def of(cls, rows: Iterable[tuple[int, PlacedBuilding, str | None]]) -> Sorters:
        """Index the sorters of one placement."""
        return cls(rows)

    def _ordered(self, records: Iterable[_SorterRecord]) -> tuple[int, ...]:
        return tuple(sorted((r.index for r in records), key=self._rank.__getitem__))

    def drawing_from(self, source: int) -> tuple[int, ...]:
        """Sorters whose ``input_obj`` is ``source``, in placement order."""
        return self._ordered(self._table.by.input_obj[source])

    def feeding(self, destination: int) -> tuple[int, ...]:
        """Sorters whose ``output_obj`` is ``destination``, in placement order."""
        return self._ordered(self._table.by.output_obj[destination])

    def carrying(self, item: str) -> tuple[int, ...]:
        """Sorters resolved to ``item``, in placement order."""
        return self._ordered(self._table.by.item[item])

    def drawing_from_carrying(self, source: int, item: str) -> tuple[int, ...]:
        """Sorters drawing from ``source`` that carry ``item``."""
        return tuple(i for i in self.drawing_from(source) if self._items[i] == item)

    def feeding_carrying(self, destination: int, item: str) -> tuple[int, ...]:
        """Sorters feeding ``destination`` that carry ``item``."""
        return tuple(i for i in self.feeding(destination) if self._items[i] == item)

    def building(self, index: int) -> PlacedBuilding:
        """The placed sorter at ``index``, handed back unchanged."""
        return self._payloads[index]

    def item(self, index: int) -> str | None:
        """The resolved item for the sorter at ``index``."""
        return self._items[index]

    def indices(self) -> tuple[int, ...]:
        """Every sorter index, in placement order."""
        return self._order
