"""Hierarchical layout: cut a spec into blocks, solve them apart, compose.

Only the strategy is re-exported.  The four modules under it -- ``partition``,
``pressure``, ``contracts`` and ``compose`` -- are imported by path, so a caller
reaching for one of them says which stage of the hierarchy it means.
"""

from __future__ import annotations

from flab2bp.layout.hierarchy.strategy import HierarchicalLayout

__all__ = ["HierarchicalLayout"]
