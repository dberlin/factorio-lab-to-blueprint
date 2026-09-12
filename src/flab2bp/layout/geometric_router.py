"""Complete directed interval routing on an already admitted query graph.

An affine label covers an integer X interval in one (Y, level) row. Horizontal
min-plus closure expands whole free, constant-price runs; other moves translate
intervals and intersect landing and ramp-via profiles. Lower envelopes retain
cheapest arrivals and immutable predecessors retain their physical witnesses.
No cell-priority search and no A* fallback are used.
"""

from __future__ import annotations

from array import array
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from ._geometric_kernel import search_intervals
from .geometric_world import GeometricWorld


class GeometricMetrics(TypedDict):
    """Native query accounting; geometric work is not A* expansion count.

    ``charged_work`` is scanned occupancy/history cells plus processed active
    intervals, including the bounded reverse probe (at most min(max_work/16,
    1024) work). Forward search receives only the remaining allowance. Offers,
    profile intersections, and selected-path certification are measured
    separately. All native inner loops also enforce the deadline.
    ``certified_edges`` counts directed edge checks during certification, not
    the selected path's length. ``retained_native_bytes`` is an accounted
    storage lower bound: it excludes Python inputs, unused heap capacity, and
    temporary allocation peaks, and is not peak resident memory.
    """

    charged_work: int
    prepared_cells: int
    interval_pops: int
    labels: int
    offers: int
    intersections: int
    profile_scans: int
    certified_edges: int
    retained_native_bytes: int
    copied_history_cells: int
    preparation_s: float
    search_s: float
    certification_s: float


@dataclass(frozen=True, slots=True)
class GeometricQuery:
    """Caller-admitted graph and limits with borrowed congestion buffers.

    Cell prices are ``pressure * (present + history)``; present is already
    scaled by the caller. By default only landings are charged. Relaxed
    congestion routing also charges each start and occupied ramp-via cell.
    Cancellation returns no witness; callback exceptions propagate.
    """

    world: GeometricWorld
    starts: tuple[int, ...]
    goals: tuple[int, ...]
    pressure: float
    max_work: int
    deadline: float | None = None
    extra_edges: Mapping[int, tuple[tuple[int, float], ...]] = field(default_factory=dict)
    present: array[float] | None = None
    charge_occupied_cells: bool = False
    cancelled: Callable[[], bool] | None = None


@dataclass(frozen=True, slots=True)
class GeometricResult:
    """Certified path, budget/cancellation refusal, or reachable rows.

    Reachability intervals are ``(y, z, lo_x, hi_x)`` in grid-local coordinates.
    ``reachable`` is the complete source component on forward exhaustion;
    ``co_reachable`` is the complete goal-reaching component on reverse
    exhaustion (``None`` means no reverse proof). Neither component is supplied
    for an interrupted query.
    Path certification proves the admitted directed graph, not a factory's
    later physical transaction, source splitter, or final placement validator.
    """

    kind: Literal["routed", "budget", "exhausted", "cancelled"]
    path: tuple[int, ...] | None
    cost: float | None
    reachable: tuple[tuple[int, int, int, int], ...]
    co_reachable: tuple[tuple[int, int, int, int], ...] | None
    metrics: GeometricMetrics


def route(query: GeometricQuery) -> GeometricResult:
    """Search the query without changing the caller's occupancy or budget."""
    world = query.world
    status, path, cost, reachable, metrics = search_intervals(
        world.flags,
        world.history,
        query.pressure,
        world.nx,
        world.ny,
        world.nz,
        world.transitions,
        query.starts,
        query.goals,
        query.extra_edges,
        query.max_work,
        query.deadline,
        query.present,
        query.charge_occupied_cells,
        query.cancelled,
    )
    kind: Literal["routed", "budget", "exhausted", "cancelled"]
    if status == 0:
        kind = "routed"
    elif status == 1:
        kind = "budget"
    elif status == 3:
        kind = "cancelled"
    else:
        kind = "exhausted"
    co_reachable = reachable if status == 4 else None
    if status == 4:
        reachable = ()
    return GeometricResult(kind, path, cost, reachable, co_reachable, metrics)
