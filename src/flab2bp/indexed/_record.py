"""The row wrapper every littletable-backed domain type inserts.

littletable assigns attributes to the rows it holds (it stamps an id on inserted
objects and rebinds fields on `Table.insert`), and every payload this codebase
would otherwise insert -- `PlacedBuilding`, `CellResult`, `_Net` -- is declared
`@dataclass(frozen=True, slots=True)`. A slotted frozen object cannot take a new
attribute, so inserting one raises rather than indexing it.

So the tables hold a wrapper: an ORDINARY dataclass (no `slots`, not frozen)
carrying the key fields flat, plus `payload`, the caller's own object handed
back unchanged. Callers never see this type; it is an implementation detail of
`flab2bp.indexed`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class IndexRecord:
    """Base for a littletable row: flat key fields plus an untouched payload."""

    payload: Any
