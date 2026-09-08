"""Sorters queried by shared placement links and context-resolved cargo.

``Buildings`` owns input/output link indexes. This collection retains only
the littletable resolved-item index: cargo attribution belongs to the
validation context and can differ from a building's ``carries_item``.

Every answer follows the supplied rows' order, even for a reordered subset
of the placement. Shared link buckets contain original positional identities;
intersecting with the rows and applying their rank preserves that contract.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING

import littletable

from flab2bp.indexed._record import IndexRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flab2bp.layout.base import PlacedBuilding
    from flab2bp.layout.buildings import Buildings


@dataclass
class _SorterRecord(IndexRecord):
    index: int = -1
    item: str | None = None


class Sorters:
    """One placement's sorters, answered by key instead of by scan."""

    def __init__(
        self, buildings: Buildings, rows: Iterable[tuple[int, PlacedBuilding, str | None]]
    ) -> None:
        table: littletable.Table = littletable.Table("sorters")
        table.create_index("item")
        order: list[int] = []
        payloads: dict[int, PlacedBuilding] = {}
        items: dict[int, str | None] = {}
        for index, building, item in rows:
            table.insert(
                _SorterRecord(
                    payload=building,
                    index=index,
                    item=item,
                )
            )
            order.append(index)
            payloads[index] = building
            items[index] = item
        self._table = table
        self._buildings = buildings
        self._order = tuple(order)
        self._payloads = payloads
        self._items = items
        self._rank = {index: rank for rank, index in enumerate(order)}

    @classmethod
    def of(
        cls, buildings: Buildings, rows: Iterable[tuple[int, PlacedBuilding, str | None]]
    ) -> Sorters:
        """Index rows whose indices identify sorters in ``buildings``.

        Pass the placement's shared immutable Buildings index; rows may be a
        reordered subset, with each payload belonging to its original position.
        Resolved items remain specific to this collection's validation context.
        """
        return cls(buildings, rows)

    def _ordered(self, records: Iterable[_SorterRecord]) -> tuple[int, ...]:
        return tuple(sorted((r.index for r in records), key=self._rank.__getitem__))

    def _ordered_links(self, indices: Iterable[int]) -> tuple[int, ...]:
        return tuple(sorted((i for i in indices if i in self._rank), key=self._rank.__getitem__))

    def drawing_from(self, source: int) -> tuple[int, ...]:
        """Sorters whose ``input_obj`` is ``source``, in placement order."""
        return self._ordered_links(self._buildings.sorters_out_of(source))

    def feeding(self, destination: int) -> tuple[int, ...]:
        """Sorters whose ``output_obj`` is ``destination``, in placement order."""
        return self._ordered_links(self._buildings.sorters_into(destination))

    def carrying(self, item: str) -> tuple[int, ...]:
        """Sorters resolved to ``item``, in placement order."""
        return self._ordered(self._table.by.item[item])

    def carrying_or_unknown(self, item: str) -> tuple[int, ...]:
        """Named and unattributable cargo, interleaved in placement order."""
        return self._ordered(chain(self._table.by.item[item], self._table.by.item[None]))

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
