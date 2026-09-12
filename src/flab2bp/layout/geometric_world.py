"""Per-query view of the caller's admitted routing graph.

Occupancy and history are borrowed, not rebuilt from the physical canvas. The
view must not survive a query: reservations and repair histories can change on
the same grid object without changing its identity. The caller must not mutate
either borrowed buffer while the synchronous query is running.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .route_feedback import Cell
    from .routing_domain import _Grid, _RoutingTransition

# (dx, dy, dz, requires source-plane ramp via, forward base cost)
GeometricTransition = tuple[int, int, int, bool, float]


@dataclass(frozen=True, slots=True)
class GeometricWorld:
    """Borrowed flat graph with authoritative directed movements."""

    nx: int
    ny: int
    nz: int
    gx0: int
    gy0: int
    flags: bytearray
    history: array[float] | list[float] | None
    transitions: tuple[tuple[GeometricTransition, ...], ...]

    @classmethod
    def from_grid(
        cls,
        grid: _Grid,
        flags: bytearray,
        transitions: tuple[tuple[_RoutingTransition, ...], ...],
    ) -> GeometricWorld:
        """Use the caller's final flags after source and forbidden overrides."""
        return cls(
            nx=grid.size // grid.xstep,
            ny=grid.gh,
            nz=grid.levels,
            gx0=grid.gx0,
            gy0=grid.gy0,
            flags=flags,
            history=grid.hist,
            transitions=tuple(
                tuple(
                    (dx, dy, offset - dx * grid.xstep - dy * grid.levels, via != 0, cost)
                    for offset, via, dx, dy, cost in row
                )
                for row in transitions
            ),
        )

    def cell(self, index: int) -> Cell:
        """Decode the same flat index used by the routing grid."""
        column, z = divmod(index, self.nz)
        x, y = divmod(column, self.ny)
        return x + self.gx0, y + self.gy0, z
