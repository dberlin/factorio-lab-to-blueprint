"""Mutable cell reservations with a reverse lookup preserving forward-map order.

A port may own several access/exit cells. Reassigning an existing cell does
not change its insertion position; deleting and reinserting it does. Those
are the dict semantics the boundary router's former first-match scan used.
All MutableMapping mutations pass through the same two indexed writers.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, MutableMapping

Cell = tuple[int, int, int]


class PortReservations(MutableMapping[Cell, Cell]):
    """One canvas's reservations, indexed by their owning port."""

    __slots__ = ("_cells", "_next_order", "_order", "_ports")

    def __init__(
        self, values: Mapping[Cell, Cell] | Iterable[tuple[Cell, Cell]] | None = None
    ) -> None:
        self._cells: dict[Cell, Cell] = {}
        self._ports: dict[Cell, set[Cell]] = {}
        self._order: dict[Cell, int] = {}
        self._next_order: int = 0
        if values is not None:
            self.update(values)

    def __getitem__(self, cell: Cell) -> Cell:
        return self._cells[cell]

    def __setitem__(self, cell: Cell, port: Cell) -> None:
        if cell in self._cells:
            prior = self._cells[cell]
            if prior == port:
                return
            self._ports[prior].remove(cell)
            if not self._ports[prior]:
                del self._ports[prior]
        else:
            self._order[cell] = self._next_order
            self._next_order += 1
        self._cells[cell] = port
        self._ports.setdefault(port, set()).add(cell)

    def __delitem__(self, cell: Cell) -> None:
        port = self._cells.pop(cell)
        del self._order[cell]
        self._ports[port].remove(cell)
        if not self._ports[port]:
            del self._ports[port]

    def __iter__(self) -> Iterator[Cell]:
        return iter(self._cells)

    def __len__(self) -> int:
        return len(self._cells)

    def clear(self) -> None:
        self._cells.clear()
        self._ports.clear()
        self._order.clear()
        self._next_order = 0

    def popitem(self) -> tuple[Cell, Cell]:
        if not self._cells:
            raise KeyError("popitem(): mapping is empty")
        cell = next(reversed(self._cells))
        port = self._cells[cell]
        del self[cell]
        return cell, port

    def first_for(self, port: Cell) -> Cell | None:
        """The first reserved cell for this port in forward insertion order."""
        return min(self._ports.get(port, ()), key=self._order.__getitem__, default=None)
