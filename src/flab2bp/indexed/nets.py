"""Prepared routing nets, keyed by id, by role, and by demand signature.

Backend: littletable. Real source read at HEAD (`layout/freeform.py`,
`master@2e861af0`) -- the plan's line anchors (:9425, :9372, :12111-12129)
are stale (Ruling P-2); the shapes below are what actually exists.

Two separate, independently-frozen collections in `freeform.py` carry this
same trio of key shapes, at different phases of one pack attempt:

* Inside `_prepare_routing_problem` (~16440), over `_PreparedNet`:
  `all_prepared_nets = tuple(... for prepared in (*prepared_nets,
  *prepared_output_nets) if not prepared.prelinked)` (~17247), then
  `net_by_id = {prepared.net_id: prepared for prepared in all_prepared_nets}`
  (~17250, id key) and `matches_demand(prepared, demand)` (~17295-17312), a
  hand-rolled item/kind/cell predicate asked with `next(... for candidate in
  all_prepared_nets if matches_demand(...))` inside a comprehension over
  every missing demand (~17314-17324) -- O(missing x all_prepared_nets).
  `matches_demand`'s "kind" is `PortAccessKind` (BOUNDARY_ARRIVAL,
  EARLY_BOUNDARY_DEPARTURE, INTERNAL_DEPARTURE, INTERNAL_ARRIVAL); each
  value picks source-or-destination as the cell to compare and a role class
  to require, which is a caller-side concern -- `Nets` stores whatever
  `(item, kind, cell)` triple the caller resolves that predicate to per row,
  not the four-way `PortAccessKind` dispatch itself.
* Inside `_route_all` (~9318), over `_Net`: `role_members: dict[tuple[Cell,
  str], set[int]]` (~9368, built ~9368-9376 from each net's src/dst role
  tuples) and `net_by_id = {_net_id(index): net for index, net in
  enumerate(nets)}` (~9432, id key). `nets: list[_Net]` is a parameter, never
  appended to inside the function -- verified at HEAD, no `nets.append`/
  `nets +=` anywhere in `_route_all`'s body.

Both collections are frozen for their own query phase: `all_prepared_nets`
is local to `_prepare_routing_problem` and never grows after ~17247; `nets`
inside `_route_all` is a parameter the rip-up-and-reroute loop mutates
`paths`/`owner` against, never the net list itself. Ruling 2 (one backend
per collection, no fourth hand-built dict) is why this is ONE type rather
than one dict per site: Task 26 indexes each collection through its own
`Nets.of(...)` call, built from that collection's own rows.

polars is refused because `_Net`/`_PreparedNet` carry nested endpoint
tuples (`src`/`dst`) that do not flatten into columns without losing what
the callers read, and both collections are hundreds of rows at most --
`Nets.of` takes bare tuples rather than importing `freeform` so that this
module stays outside the `freeform` -> `indexed` direction Task 26 will add.

Order is input order in every accessor, matching the comprehensions and
dict/set iterations replaced. littletable's `by.field[value]` returns
records in TABLE INSERTION order, not any order derived from the key's
value (checked directly, same finding `Sorters` and `Cells` record) --
accessors resort explicitly by each row's position in the `rows` `Nets.of`
was given, rather than trusting that coincidence to hold across littletable
versions.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import littletable

from flab2bp.indexed._record import IndexRecord

Cell = tuple[int, int, int]


@dataclass
class _NetRecord(IndexRecord):
    net_id: int = -1
    role: str = ""
    signature: tuple[str, str, Cell] = ("", "", (0, 0, 0))
    position: int = -1


class Nets:
    """One pack attempt's prepared nets, answered by key instead of by scan."""

    def __init__(self, rows: Iterable[tuple[int, str, str, Cell, str, Any]]) -> None:
        table: littletable.Table = littletable.Table("nets")
        table.create_index("net_id", unique=True)
        table.create_index("role")
        table.create_index("signature")
        ids: list[int] = []
        for position, (net_id, item, kind, cell, role, payload) in enumerate(rows):
            table.insert(
                _NetRecord(
                    payload=payload,
                    net_id=net_id,
                    role=role,
                    signature=(item, kind, cell),
                    position=position,
                )
            )
            ids.append(net_id)
        self._table = table
        self._ids = tuple(ids)

    @classmethod
    def of(cls, rows: Iterable[tuple[int, str, str, Cell, str, Any]]) -> Nets:
        """Index one pack attempt's prepared nets."""
        return cls(rows)

    def ids(self) -> tuple[int, ...]:
        """Every net id, in preparation order."""
        return self._ids

    def by_id(self, net_id: int) -> Any | None:
        """The net with that id, or ``None``."""
        # A `unique=True` index answers the row directly and raises `KeyError`
        # when absent, unlike every other (non-unique) index here, which
        # answers an iterable `Table` -- checked directly against a live
        # littletable table.
        try:
            record = self._table.by.net_id[net_id]
        except KeyError:
            return None
        return record.payload

    def matching_demand(self, item: str, kind: str, cell: Cell) -> tuple[Any, ...]:
        """Nets whose demand signature is exactly ``(item, kind, cell)``."""
        records = sorted(self._table.by.signature[(item, kind, cell)], key=lambda r: r.position)
        return tuple(record.payload for record in records)

    def in_role(self, role: str) -> tuple[int, ...]:
        """Net ids in one role, in preparation order."""
        records = sorted(self._table.by.role[role], key=lambda r: r.position)
        return tuple(record.net_id for record in records)
