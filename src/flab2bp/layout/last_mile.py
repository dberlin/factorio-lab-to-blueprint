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
is behind ``TYPE_CHECKING`` and every capability the search needs arrives as a
callable on :class:`ClusterEnvironment`, because ``_route_all``'s ends, stake,
unstake and blocker machinery are closures over one routing pass and cannot be
imported.  (``route_feedback`` IS a runtime import -- the ``BUDGET`` rule
compares against :class:`RouteFailureKind`, and that module imports nothing
from here, so there is no cycle.)
That also makes the whole module testable on hand-built grids.
"""

from __future__ import annotations

import heapq
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from flab2bp.layout.route_feedback import ClusterRelationNoGood, RouteFailureKind

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flab2bp.layout.freeform import _PathSearchResult

Cell = tuple[int, int, int]

#: One net's ``_ends`` offer maps, as the caller hands them back at stake time.
_Offers = tuple[Mapping[Cell, Cell], Mapping[Cell, Cell], Mapping[Cell, Cell]]

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

#: Remaining wall seconds below which the pass declines to start.  MEASURED,
#: not guessed: ``scripts/last_mile_bench.py``'s two corpus captures put the
#: slowest observed cluster search at 0.909 s (``universe-matrix``,
#: ``output-products``), so twice that, rounded up, is the margin a pass needs
#: to finish what it starts rather than be cut by the deadline mid-tree.  See
#: ``docs/superpowers/evidence/2026-09-02-phase-b-last-mile/cluster-bench.txt``.
B_MIN_SECONDS = 1.82

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


class ClusterBound(StrEnum):
    """Which bound ended a run, so a replay can tell a wall cut from a cap."""

    NONE = ""
    NODES = "nodes"
    CONSTRAINTS = "constraints"
    BUDGET = "budget"
    WALL = "wall"


@dataclass(frozen=True, slots=True)
class ClusterResult:
    """What one cluster search established, and what it cost."""

    outcome: ClusterOutcome
    paths: Mapping[int, tuple[Cell, ...]]
    nodes: int
    expansions: int
    seconds: float
    bound: ClusterBound = ClusterBound.NONE

    def __post_init__(self) -> None:
        if self.outcome is not ClusterOutcome.SOLVED and self.paths:
            raise ValueError("only a solved cluster carries paths")
        if self.outcome is ClusterOutcome.SOLVED and not self.paths:
            raise ValueError("a solved cluster carries a path for every net")
        # The result does not carry the cluster's net list, so "one path per
        # net" is not checkable here; :func:`solve_cluster` gates the SOLVED
        # return on ``len(paths) == len(problem.nets)``, which is where the net
        # list exists.  What IS checkable here is that no entry is a placeholder:
        # an empty tuple is not a route, so a mapping carrying one would make the
        # count above agree while a net still had nowhere to go.
        if any(not path for path in self.paths.values()):
            raise ValueError("a cluster path is a real, non-empty run of cells")
        if (self.bound is ClusterBound.NONE) is (self.outcome is ClusterOutcome.BOUNDED):
            raise ValueError("a bounded run names its bound and no other does")


@dataclass(frozen=True, slots=True)
class ClusterEnvironment:
    """Everything the search may do, as callables owned by the caller.

    ``search(index, forbidden)`` must run the caller's own A* for one net with
    the caller's own ends, its own rejected-commit cells UNIONED with
    ``forbidden``, and the cluster's paths absent from the grid.  The search
    never touches a canvas itself; the caller owns every mutation.

    ``offers`` re-queries one net's ``_ends`` offer maps.  :func:`solve_cluster`
    never calls it; it is here because the caller needs it at STAKE time and
    the environment is the object that already knows how to reach ``_ends``.
    Offers collected during the search are stale by then -- staking happens one
    net at a time and each stake takes cells the next net's offers were
    computed against.
    """

    search: Callable[[int, frozenset[Cell]], _PathSearchResult]
    offers: Callable[[int], _Offers]
    budget_left: Callable[[], int]
    budget_floor: int
    expired: Callable[[], bool]
    max_nodes: int = B_MAX_CBS_NODES
    max_constraints: int = B_MAX_CONSTRAINTS


_Constraints = tuple[tuple[int, Cell], ...]
_Node = tuple[tuple[int, int, int], _Constraints, dict[int, tuple[Cell, ...]]]


def _cost(problem: ClusterProblem, paths: Mapping[int, tuple[Cell, ...]]) -> int:
    return sum(
        len(paths[index]) if index in paths else B_UNROUTED_COST for index in problem.nets
    )


def _first_conflict(
    problem: ClusterProblem,
    paths: Mapping[int, tuple[Cell, ...]],
) -> tuple[int, int, Cell] | None:
    """The first cell two cluster paths share, scanning nets in index order.

    A cell is ``(x, y, level)``, which is the whole resource: a ramp's ``via``
    cell is already spliced into the path by ``_astar`` and de-duplicated by
    ``_cut_loops``, so ramps need no separate model, and two paths crossing one
    column at different levels are correctly not a conflict.
    """
    seen: dict[Cell, int] = {}
    for index in problem.nets:
        path = paths.get(index)
        if path is None:
            continue
        for cell in path:
            holder = seen.get(cell)
            if holder is not None and holder != index:
                return (holder, index, cell)
            seen[cell] = index
    return None


def _forbidden_for(constraints: _Constraints, net: int) -> frozenset[Cell]:
    return frozenset(cell for index, cell in constraints if index == net)


def solve_cluster(
    problem: ClusterProblem,
    environment: ClusterEnvironment,
) -> ClusterResult:
    """Conflict-based search over ``problem``, bounded by ``environment``.

    High level: best-first over the sum of path lengths, splitting the first
    shared cell into the two one-net constraints.  A branch that loses a net
    is kept and priced, never dropped, because a dropped branch would make a
    closed tree a lie.  Reaching any bound ends the run as BOUNDED for the same
    reason: only a heap that empties on its own, with every search in it having
    reached a real conclusion, is a proof.

    A low-level result carrying :attr:`RouteFailureKind.BUDGET` is the subtle
    version of that: the search did not decide whether a path exists, so the
    node built on it does not stand for the subspace it claims, and an empty
    heap afterwards is an artifact of the cap rather than a fact about the
    grid.  Every such result ends the run.
    """
    started = time.perf_counter()
    entry_budget = environment.budget_left()

    def done(
        outcome: ClusterOutcome,
        paths: Mapping[int, tuple[Cell, ...]],
        nodes: int,
        bound: ClusterBound = ClusterBound.NONE,
    ) -> ClusterResult:
        return ClusterResult(
            outcome=outcome,
            paths=dict(paths) if outcome is ClusterOutcome.SOLVED else {},
            nodes=nodes,
            expansions=entry_budget - environment.budget_left(),
            seconds=time.perf_counter() - started,
            bound=bound,
        )

    def hit_bound() -> ClusterBound:
        if environment.expired():
            return ClusterBound.WALL
        if environment.budget_left() <= environment.budget_floor:
            return ClusterBound.BUDGET
        return ClusterBound.NONE

    def cut(found: _PathSearchResult) -> bool:
        return found.kind is RouteFailureKind.BUDGET

    if (bound := hit_bound()) is not ClusterBound.NONE:
        return done(ClusterOutcome.BOUNDED, {}, 0, bound)

    root: dict[int, tuple[Cell, ...]] = {}
    for index in problem.nets:
        if (bound := hit_bound()) is not ClusterBound.NONE:
            return done(ClusterOutcome.BOUNDED, {}, 0, bound)
        found = environment.search(index, frozenset())
        if cut(found):
            return done(ClusterOutcome.BOUNDED, {}, 0, ClusterBound.BUDGET)
        if found.path is not None:
            root[index] = found.path

    ordinal = 0
    heap: list[_Node] = [((_cost(problem, root), 0, ordinal), (), root)]
    nodes = 0
    while heap:
        if nodes >= environment.max_nodes:
            return done(ClusterOutcome.BOUNDED, {}, nodes, ClusterBound.NODES)
        if (bound := hit_bound()) is not ClusterBound.NONE:
            return done(ClusterOutcome.BOUNDED, {}, nodes, bound)
        _key, constraints, paths = heapq.heappop(heap)
        nodes += 1
        conflict = _first_conflict(problem, paths)
        if conflict is None:
            if len(paths) == len(problem.nets):
                return done(ClusterOutcome.SOLVED, paths, nodes)
            # Conflict-free but incomplete: no split can add a path, so the
            # branch is exhausted rather than bounded.
            continue
        left, right, cell = conflict
        for chosen in (left, right):
            child_constraints: _Constraints = (*constraints, (chosen, cell))
            if len(child_constraints) > environment.max_constraints:
                return done(ClusterOutcome.BOUNDED, {}, nodes, ClusterBound.CONSTRAINTS)
            if (bound := hit_bound()) is not ClusterBound.NONE:
                return done(ClusterOutcome.BOUNDED, {}, nodes, bound)
            found = environment.search(chosen, _forbidden_for(child_constraints, chosen))
            if cut(found):
                return done(ClusterOutcome.BOUNDED, {}, nodes, ClusterBound.BUDGET)
            child = dict(paths)
            if found.path is None:
                child.pop(chosen, None)
            else:
                child[chosen] = found.path
            ordinal += 1
            heapq.heappush(
                heap,
                (
                    (_cost(problem, child), len(child_constraints), ordinal),
                    child_constraints,
                    child,
                ),
            )
    return done(ClusterOutcome.PROVED, {}, nodes)


def relation_no_good(
    *,
    strips: Sequence[int],
    origins: Sequence[tuple[int, int]],
    outline: tuple[tuple[int, int], ...],
    height: int,
    evidence: str,
) -> ClusterRelationNoGood | None:
    """Record the cluster strips' relative placement, or nothing to record."""
    chosen = tuple(sorted({strip for strip in strips if 0 <= strip < len(origins)}))
    if len(chosen) < 2:
        return None
    anchor = origins[chosen[0]]
    deltas = tuple(
        (origins[strip][0] - anchor[0], origins[strip][1] - anchor[1])
        for strip in chosen
    )
    return ClusterRelationNoGood(
        height=height,
        outline=tuple(outline),
        strips=chosen,
        deltas=deltas,
        evidence=(evidence,),
    )


@dataclass(frozen=True, slots=True)
class ClusterCapture:
    """Everything a replay needs to re-run one live cluster search."""

    run: int                       # 1 environment run, 2 relaxed run
    canvas: object                 # freeform._Canvas, opaque here
    grid: object                   # freeform._Grid, opaque here
    history: Mapping[Cell, float]
    pressure: float
    bounds: tuple[int, int, int, int]
    problem: ClusterProblem
    ends: Mapping[int, tuple[list[Cell], set[Cell], frozenset[Cell]]]
    budget_left: int
    budget_floor: int
    deadline_remaining: float | None
    #: The REST of what the caller's ``search`` hands its A*, per net.  A
    #: replay that omits these is not the same search: an owned start is a
    #: junction-guard cell the low level makes PASSABLE, so dropping it moves
    #: the path, and a rejected-commit cell is subtracted from the same flags.
    owned_starts: Mapping[int, frozenset[Cell]]
    rejected: Mapping[int, frozenset[Cell]]
    #: Cell ownership, for the blame wall a refused search reports.  It steers
    #: no path, but it is an input the live search had and the replay would
    #: otherwise fabricate.
    blocking_owners: Mapping[Cell, int]


#: Developer-tool hook.  ``None`` in production; ``scripts/route_bench.py``
#: sets it for the length of one capture run.  A module-level callback rather
#: than a parameter because the alternative is threading a bench-only argument
#: through ``lay_out``, ``_sweep``, ``_build`` and ``_build_prepared``.
CAPTURE: Callable[[ClusterCapture], None] | None = None
