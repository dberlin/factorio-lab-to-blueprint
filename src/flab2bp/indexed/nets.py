"""Prepared routing nets, keyed by id, by (cell, role), and by demand signature.

Backend: littletable. Real source read at HEAD (`layout/freeform.py`,
`master@2e861af0`) -- the plan's line anchors (:9425, :9372, :12111-12129)
are stale (Ruling P-2); the shapes below are what actually exists, verified
directly against the tree in two review rounds.

At least THREE separate, independently-frozen collections in `freeform.py`
carry net_by_id-shaped or role-shaped lookups, at different phases of one
pack attempt:

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
* Inside `_route_all` (~9318), over `_Net`: `net_by_id = {_net_id(index):
  net for index, net in enumerate(nets)}` (~9432, id key) and
  `role_members: dict[tuple[Cell, str], set[int]]` (~9368), built ~9368-9376
  from each net's role tuples -- EVERY net contributes a `"dst"` entry, and
  a `"src"` entry too when `net.src is not None`, so a net can appear under
  up to two DIFFERENT `(cell, role)` composite keys. Queried at ~9889 as
  `role_members[token]` where `token = (key, role)` -- confirmed directly:
  the key is the COMPOSITE `(cell, role)`, not a bare role, and the call
  site is a plain membership test (`any(... for member in
  role_members[token])`), not order-sensitive. `nets: list[_Net]` is a
  parameter, never appended to inside the function -- verified at HEAD, no
  `nets.append`/`nets +=` anywhere in `_route_all`'s body.
* Inside `_prepared_routing_lower_bound` (~8928), over `_PreparedNet`:
  `nets = tuple(net for net in (*problem.nets, *problem.external_output_nets)
  if not net.prelinked)`, then `net_by_id = {net.net_id: net for net in
  nets}` (~8956, id key) and `parent = {net_id: net_id for net_id in
  net_by_id}` (~8957) -- a plain "every id, in order" walk of the dict's
  keys, matching `ids()` exactly. `net_by_id.get(net_id)` (~8993, ~8999)
  matches `by_id`'s None-on-absent contract exactly.

All three collections are frozen for their own query phase (each is local
to its function and never appended to after construction -- verified
directly, not assumed). Ruling 2 (one backend per collection, no fourth
hand-built dict) is why this is ONE type rather than one dict per site:
Task 26 indexes each collection through its own `Nets.of(...)` call, built
from that collection's own rows.

BECAUSE a net can occupy two roles at two different cells (the `_route_all`
collection above), `net_id` is NOT unique across a `Nets` table in general:
a `_route_all`-shaped instance carries up to two rows per net, one per
`(cell, role)` entry, sharing one `payload` (the same `_Net` object) and one
`net_id`. `by_id` and `ids()` account for this: `by_id` returns the first
row's payload in preparation order (rows sharing a net_id carry an
identical payload, so which one is "first" is unobservable), and `ids()`
answers each DISTINCT net id once, in first-seen order -- not once per row
-- matching what `net_by_id`'s dict keys and `role_members`'s per-id
membership tests actually hand callers.

`in_role` takes the composite `(cell, role)`, matching `role_members`'s real
key shape; a bare-role query was dropped after the first review round found
no real call site asks for "every net in role X" across every cell -- every
real site scopes by cell too. `role` is still stored on each row (needed to
build the composite) but is not separately indexed, since nothing queries
it alone.

polars is refused because `_Net`/`_PreparedNet` carry nested endpoint
tuples (`src`/`dst`) that do not flatten into columns without losing what
the callers read, and every collection above is hundreds of rows at most --
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

from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from typing import Any

import littletable

from flab2bp.indexed._record import IndexRecord

Cell = tuple[int, int, int]


@dataclass
class _NetRecord(IndexRecord):
    net_id: Hashable = -1
    role: str = ""
    signature: tuple[str, str, Cell] = ("", "", (0, 0, 0))
    cell_role: tuple[Cell, str] = ((0, 0, 0), "")
    position: int = -1


class Nets[Id: Hashable]:
    """Frozen query-phase keys and row order, with unchanged live payload identity.

    Keys are supplied independently of the opaque payload and captured at
    construction. Callers must keep identity-bearing payload fields immutable
    for this phase; a replacement endpoint/identity requires a new phase index.
    Non-key payload state may remain mutable and is never copied by this owner.
    """

    def __init__(self, rows: Iterable[tuple[Id, str, str, Cell, str, Any]]) -> None:
        """Capture each row's keys once; retain, rather than clone, its payload."""
        table: littletable.Table = littletable.Table("nets")
        table.create_index("net_id")
        table.create_index("signature")
        table.create_index("cell_role")
        ids: list[Id] = []
        for position, (net_id, item, kind, cell, role, payload) in enumerate(rows):
            table.insert(
                _NetRecord(
                    payload=payload,
                    net_id=net_id,
                    role=role,
                    signature=(item, kind, cell),
                    cell_role=(cell, role),
                    position=position,
                )
            )
            ids.append(net_id)
        self._table = table
        self._ids = tuple(dict.fromkeys(ids))

    @classmethod
    def of(cls, rows: Iterable[tuple[Id, str, str, Cell, str, Any]]) -> Nets[Id]:
        """Index one immutable-key phase of prepared or detailed routing nets."""
        return cls(rows)

    def ids(self) -> tuple[Id, ...]:
        """Every DISTINCT net id, first-seen order (never once per role row)."""
        return self._ids

    def by_id(self, net_id: Id) -> Any | None:
        """The net with that id, or ``None``.

        A net_id is not unique across the table in general (a net can carry
        up to two rows, one per role -- see the module docstring), so this
        answers the first row in preparation order. Rows sharing a net_id
        always carry an identical payload, so "first" is unobservable.
        """
        records = sorted(self._table.by.net_id[net_id], key=lambda r: r.position)
        return records[0].payload if records else None

    def matching_demand(self, item: str, kind: str, cell: Cell) -> tuple[Any, ...]:
        """Nets whose demand signature is exactly ``(item, kind, cell)``."""
        records = sorted(self._table.by.signature[(item, kind, cell)], key=lambda r: r.position)
        return tuple(record.payload for record in records)

    def in_role(self, cell: Cell, role: str) -> tuple[Id, ...]:
        """Net ids occupying one role at one cell, in preparation order."""
        records = sorted(self._table.by.cell_role[(cell, role)], key=lambda r: r.position)
        return tuple(record.net_id for record in records)

    def roles_of(self, net_id: Id) -> tuple[tuple[Cell, str], ...]:
        """This net's endpoint roles, in the original row order."""
        records = sorted(self._table.by.net_id[net_id], key=lambda r: r.position)
        return tuple(record.cell_role for record in records)

    def payloads_in_role(self, cell: Cell, role: str) -> tuple[Any, ...]:
        """The payloads occupying a cell-role, in preparation order."""
        records = sorted(self._table.by.cell_role[(cell, role)], key=lambda r: r.position)
        return tuple(record.payload for record in records)
