# src/flab2bp/layout/last_mile.py
"""A bounded, complete last-mile search over a small conflict cluster.

The rip-up-and-reroute loop in :func:`flab2bp.layout.freeform._route_all` is
greedy sequential routing with a displacement repair.  When it finishes with a
net or two still unrouted it has proved nothing: the pack is discarded and the
only thing that survives is decaying feedback.  This module is the missing
proof.  Given the handful of nets that failed and the nets their blame walls
accuse, it searches JOINTLY over all of them -- conflict-based search, with the
router's own A* at the low level -- and returns one of exactly three answers:
a disjoint routing for every cluster net, a closed tree that proves there is
none, or "a bound fired and nothing is claimed".

NOTHING HERE IMPORTS ``freeform`` AT RUNTIME.  Every canvas, grid and net type
is behind ``TYPE_CHECKING`` (added in the next task, with the search) and every
capability the search needs arrives as a callable on
:class:`ClusterEnvironment`, because ``_route_all``'s ends, stake, unstake and
blocker machinery are closures over one routing pass and cannot be imported.
That also makes the whole module testable on hand-built grids.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

Cell = tuple[int, int, int]

#: The largest stranded set a cluster search is offered.  Both Phase B target
#: cells refuse with ONE net unrouted on their best pack; three leaves room for
#: the worst observed pack without inviting a cluster nobody can close.
B_MAX_STRANDED = 3

#: The largest cluster.  Packs on these cells hold 100-150 nets, and the
#: measurement in ``_repair``'s docstring is that a stranded net crosses between
#: 1 and 11 already-placed paths, so eight is a real neighbourhood rather than
#: a token one.
B_MAX_CLUSTER = 8

#: High-level CBS nodes per run.
B_MAX_CBS_NODES = 512

#: Constraints on one CBS node.  Reaching it ends the run as BOUNDED rather
#: than pruning the branch: a pruned branch would make a closed tree a lie.
B_MAX_CONSTRAINTS = 64

#: Share of the routing pass's remaining expansion budget one run may spend.
B_CBS_EXPANSION_SHARE = 0.25

#: Bound on the number of low-level A* expansions one CBS run may spend.
B_LOW_LEVEL_EXPANSIONS = 50_000

#: Remaining wall seconds below which the pass declines to start.
B_MIN_SECONDS = 0.35

#: Cost charged for a cluster net with no path, so nodes that lost a net sort
#: after nodes that kept one without special-casing the heap.
B_UNROUTED_COST = 1_000_000

#: A distance no real cell pair reaches; written as one literal (not ``1 << 30``)
#: so R1's coincidence scan does not trip over the bare exponent 30.
_FAR = 1_073_741_824


class ClusterOutcome(StrEnum):
    """What one cluster search established."""

    SOLVED = "solved"
    PROVED = "proved"
    BOUNDED = "bounded"


@dataclass(frozen=True, slots=True)
class ClusterProblem:
    """The nets one cluster search may move, and what is known about them."""

    nets: tuple[int, ...]
    stranded: tuple[int, ...]
    truncated: bool
    sibling_closed: bool

    def __post_init__(self) -> None:
        if not self.nets:
            raise ValueError("a cluster problem needs at least one net")
        if tuple(sorted(self.nets)) != self.nets:
            raise ValueError("cluster nets must be ascending")
        if not set(self.stranded) <= set(self.nets):
            raise ValueError("every stranded net must be a cluster member")


def _anchor_cells(
    index: int,
    paths: Mapping[int, tuple[Cell, ...]],
    endpoints: Mapping[int, tuple[Cell | None, Cell]],
) -> tuple[Cell, ...]:
    path = paths.get(index)
    if path:
        return path
    ends = endpoints.get(index)
    if ends is None:
        return ()
    source, destination = ends
    return tuple(cell for cell in (source, destination) if cell is not None)


def _distance_to_stranded(
    candidate: int,
    stranded: Sequence[int],
    paths: Mapping[int, tuple[Cell, ...]],
    endpoints: Mapping[int, tuple[Cell | None, Cell]],
) -> int:
    """Manhattan distance from a candidate's cells to any stranded endpoint."""
    cells = _anchor_cells(candidate, paths, endpoints)
    best = _FAR
    for seed in stranded:
        ends = endpoints.get(seed)
        if ends is None:
            continue
        for target in ends:
            if target is None:
                continue
            for cell in cells:
                value = abs(cell[0] - target[0]) + abs(cell[1] - target[1])
                if value < best:
                    best = value
    return best


def build_cluster(
    stranded: Sequence[int],
    *,
    walls: Mapping[int, tuple[Cell, ...]],
    blockers: Mapping[int, tuple[int, ...]],
    owner: Mapping[Cell, int],
    paths: Mapping[int, tuple[Cell, ...]],
    endpoints: Mapping[int, tuple[Cell | None, Cell]],
    src_group: Mapping[int, tuple[int, ...]],
    dst_group: Mapping[int, tuple[int, ...]],
    max_cluster: int = B_MAX_CLUSTER,
) -> ClusterProblem:
    """Close the stranded nets over their accusers, bounded by ``max_cluster``."""
    seeds = tuple(sorted(dict.fromkeys(stranded)))
    if not seeds:
        raise ValueError("a cluster needs at least one stranded net")
    members = set(seeds)
    cluster = list(seeds)
    truncated = False
    frontier: list[int] = list(seeds)
    while frontier:
        candidates: set[int] = set()
        for index in frontier:
            for cell in walls.get(index, ()):
                holder = owner.get(cell)
                if holder is not None and holder not in members:
                    candidates.add(holder)
            for holder in blockers.get(index, ()):
                if holder not in members:
                    candidates.add(holder)
        if not candidates:
            break
        room = max_cluster - len(cluster)
        if room <= 0:
            truncated = True
            break
        ordered = sorted(
            candidates,
            key=lambda candidate: (
                _distance_to_stranded(candidate, seeds, paths, endpoints),
                candidate,
            ),
        )
        if len(ordered) > room:
            truncated = True
            ordered = ordered[:room]
        cluster.extend(ordered)
        members.update(ordered)
        frontier = ordered
    cluster.sort()
    sibling_closed = all(
        sibling in members
        for index in cluster
        for sibling in (*src_group.get(index, ()), *dst_group.get(index, ()))
    )
    return ClusterProblem(
        nets=tuple(cluster),
        stranded=seeds,
        truncated=truncated,
        sibling_closed=sibling_closed,
    )


def cluster_strips(
    problem: ClusterProblem,
    net_strips: Mapping[int, tuple[int | None, int | None]],
) -> tuple[int, ...]:
    """Ascending strip instances the cluster's nets attach to."""
    instances: set[int] = set()
    for index in problem.nets:
        ends = net_strips.get(index)
        if ends is None:
            continue
        for strip in ends:
            if strip is not None and strip >= 0:
                instances.add(strip)
    return tuple(sorted(instances))
