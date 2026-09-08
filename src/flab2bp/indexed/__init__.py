"""Indexed domain types: one module per kind of collection.

This package is the ONLY place in the tree allowed to import `littletable`,
`networkx`, `polars`, `rustworkx` or `scipy`. Callers import a domain type from
here, call methods named for what they are asking, and receive the domain's own
types back -- never a `Table`, a `DataFrame`, a graph object, or a query
expression. See `docs/superpowers/plans/2026-09-07-indexed-scans.md` for the
per-collection backend table and why each backend was chosen.
"""

from __future__ import annotations

from flab2bp.indexed.belt_overlap import BeltOverlap
from flab2bp.indexed.block_graph import BlockGraph
from flab2bp.indexed.cells import Cells
from flab2bp.indexed.nets import Nets
from flab2bp.indexed.port_reservations import PortReservations
from flab2bp.indexed.reference_graph import ReferenceGraph
from flab2bp.indexed.sorters import Sorters
from flab2bp.indexed.stages import Stages
from flab2bp.indexed.staked_paths import StakedPaths
from flab2bp.indexed.strip_positions import StripPositions
from flab2bp.indexed.union_find import UnionFind

__all__: tuple[str, ...] = (
    "BeltOverlap",
    "BlockGraph",
    "Cells",
    "Nets",
    "PortReservations",
    "ReferenceGraph",
    "Sorters",
    "StakedPaths",
    "Stages",
    "StripPositions",
    "UnionFind",
)
