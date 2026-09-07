"""Indexed domain types: one module per kind of collection.

This package is the ONLY place in the tree allowed to import `littletable`,
`networkx`, `polars`, `rustworkx` or `scipy`. Callers import a domain type from
here, call methods named for what they are asking, and receive the domain's own
types back -- never a `Table`, a `DataFrame`, a graph object, or a query
expression. See `docs/superpowers/plans/2026-09-07-indexed-scans.md` for the
per-collection backend table and why each backend was chosen.
"""

from __future__ import annotations

from flab2bp.indexed.reference_graph import ReferenceGraph

__all__: tuple[str, ...] = ("ReferenceGraph",)
