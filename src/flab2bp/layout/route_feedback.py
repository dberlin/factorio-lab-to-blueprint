from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flab2bp.layout.strip_variants import StripFamilyId, StripInstanceId

from .sequence_pair import (
    DecodedPlacement,
    DirectInsertTarget,
    GapProfile,
    PlacementCostContext,
    PlacementProblem,
    SequencePair,
)
from .strip_variants import CargoDomain

Cell = tuple[int, int, int]


class NetRole(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    EXTERNAL_OUTPUT = "external-output"
    PROLIFERATOR = "proliferator"


@dataclass(frozen=True, slots=True)
class LogicalNetId:
    """Stable recipe edge identity shared by all current physical branches."""

    source_family: StripFamilyId | None
    destination_family: StripFamilyId | None
    item: str
    role: NetRole
    cargo_domain: CargoDomain = CargoDomain.UNSPRAYED
    legacy_source_strip: int | None = None
    legacy_destination_strip: int | None = None
    legacy_ordinal: int | None = None


@dataclass(frozen=True, order=True, slots=True)
class NetId:
    source_strip: int | None
    destination_strip: int | None
    item: str
    role: NetRole
    ordinal: int
    logical_id: LogicalNetId | None = None
    cargo_domain: CargoDomain = CargoDomain.UNSPRAYED

    @property
    def logical(self) -> LogicalNetId:
        """Return stable identity, deriving a legacy-local key when unavailable."""
        return self.logical_id or LogicalNetId(
            source_family=None,
            destination_family=None,
            item=self.item,
            role=self.role,
            cargo_domain=self.cargo_domain,
            legacy_source_strip=self.source_strip,
            legacy_destination_strip=self.destination_strip,
            legacy_ordinal=self.ordinal,
        )


class RouteFailureKind(StrEnum):
    STATIC_ACCESS = "static-access"
    DYNAMIC_ACCESS = "dynamic-access"
    SEALED_POCKET = "sealed-pocket"
    CONGESTION_WALL = "congestion-wall"
    COMMIT_LINK = "commit-link"
    BUDGET = "budget"


class DetailedRouteStatus(StrEnum):
    ROUTED = "routed"
    STRANDED = "stranded"
    UNPOWERABLE = "unpowerable"
    BUDGET = "budget"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class NetFailure:
    net_id: NetId
    kind: RouteFailureKind
    wall: tuple[Cell, ...]
    blocking_nets: tuple[NetId, ...]
    expansions: int
    source: Cell | None = None
    destination: Cell | None = None
    blocking_endpoints: tuple[tuple[Cell | None, Cell | None], ...] = ()

    def __post_init__(self) -> None:
        if self.blocking_endpoints and len(self.blocking_endpoints) != len(
            self.blocking_nets
        ):
            raise ValueError("blocking endpoints must align with blocking net identities")
        cells = (
            self.source,
            self.destination,
            *(
                cell
                for endpoints in self.blocking_endpoints
                for cell in endpoints
            ),
        )
        if any(cell is not None and not _coordinate_cell(cell) for cell in cells):
            raise ValueError("route failure endpoints must be integer coordinate cells")


@dataclass(frozen=True, slots=True)
class LastMileReport:
    """What the bounded last-mile cluster search did in one routing pass."""

    invocations: int
    solved: int
    proved: int
    bounded: int
    #: A CBS solution the commit preflight refused, or whose rollback ran.
    commit_rejected: int
    #: Run 1 closed but a cluster net had a sibling, so run 2 was not run.
    #: See the spec's 5.2: unstaking a sibling can DISCONNECT a net, and a
    #: closed tree over a disconnected net is a false proof.
    relation_skipped_siblings: int
    #: Times the round could not be restored exactly.  Never an exception: an
    #: `AssertionError` here becomes a CRASH row and fails the corpus gate on a
    #: condition the gate exists to measure.
    restore_mismatch: int
    nodes: int
    expansions: int
    seconds: float
    #: Ascending strip instances of a cluster proved unroutable in the relaxed
    #: environment, empty when no relation proof was established.
    relation_strips: tuple[int, ...] = ()
    relation_evidence: str = ""
    #: Stranded nets a cluster left OUT because they share an un-tappable source
    #: lane with a net it kept.  Only one net can ever leave such a lane
    #: directly, so offering the same access cells to both produced solutions
    #: the committer refused with `junction-collider`.  Defaulted, and NOT one
    #: of the eleven flattened `PlacementStats` keys: it is a diagnosis of the
    #: pass, not a corpus counter.
    same_source_dropped: int = 0

    def __post_init__(self) -> None:
        if self.relation_strips and len(self.relation_strips) < 2:
            raise ValueError("a relation proof needs at least two strip instances")
        if tuple(sorted(self.relation_strips)) != self.relation_strips:
            raise ValueError("relation strips must be ascending")


@dataclass(frozen=True, slots=True)
class ClusterRelationNoGood:
    """One relative placement of strip instances proved unroutable.

    The proof behind it is a CBS tree that closed with every OTHER belt in the
    pack unstaked and the cluster's routing-derived rejection sets emptied, so
    it is a statement about the strips and not about one routing: any packing
    that repeats these relative offsets refuses again.  ``outline`` and
    ``height`` scope it to the strip plan that produced it, the same guard
    :class:`ExactPackNoGood` carries.

    ``evidence`` is one blob rather than one string per net: what a reader
    needs is which cluster this was and that both runs closed, and a per-net
    tuple only makes the equality key noisier.
    """

    height: int
    outline: tuple[tuple[int, int], ...]
    strips: tuple[int, ...]
    deltas: tuple[tuple[int, int], ...]
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.height <= 0:
            raise ValueError("cluster relation height must be positive")
        if len(self.strips) < 2:
            raise ValueError("a cluster relation needs at least two strips")
        if any(strip < 0 for strip in self.strips):
            raise ValueError("cluster relation strips must be non-negative indices")
        if tuple(sorted(self.strips)) != self.strips:
            raise ValueError("cluster relation strips must be ascending")
        if len(self.deltas) != len(self.strips):
            raise ValueError("a cluster relation needs one delta per strip")
        if self.deltas[0] != (0, 0):
            raise ValueError("the anchor strip's delta must be the origin")
        if not self.evidence:
            raise ValueError("a cluster relation no-good requires evidence")


def combine_last_mile_reports(
    reports: Iterable[LastMileReport | None],
) -> LastMileReport | None:
    """One report for a build that routed in several stages.

    A prepared build routes external inputs, early outputs, the interior and
    late outputs as four separate passes, and EACH runs a last-mile pass of its
    own.  Reporting one of them makes every corpus counter under-read by
    however much the other three did, which is the opposite of what the
    counters exist for.

    The counters are all additive and are summed.  ``relation_strips`` and
    ``relation_evidence`` are NOT: they name one specific proof over one
    specific cluster, so the first non-empty value of each is carried whole.
    Concatenating them would manufacture a claim no single run ever made.

    Returns ``None`` when no stage reported anything, so a caller that never
    ran the pass is distinguishable from one that ran it and found nothing.
    """
    present = [report for report in reports if report is not None]
    if not present:
        return None
    return LastMileReport(
        invocations=sum(report.invocations for report in present),
        solved=sum(report.solved for report in present),
        proved=sum(report.proved for report in present),
        bounded=sum(report.bounded for report in present),
        commit_rejected=sum(report.commit_rejected for report in present),
        relation_skipped_siblings=sum(
            report.relation_skipped_siblings for report in present
        ),
        restore_mismatch=sum(report.restore_mismatch for report in present),
        nodes=sum(report.nodes for report in present),
        expansions=sum(report.expansions for report in present),
        seconds=sum(report.seconds for report in present),
        relation_strips=next(
            (report.relation_strips for report in present if report.relation_strips),
            (),
        ),
        relation_evidence=next(
            (
                report.relation_evidence
                for report in present
                if report.relation_evidence
            ),
            "",
        ),
        same_source_dropped=sum(report.same_source_dropped for report in present),
    )


@dataclass(frozen=True, slots=True)
class DetailedRouteResult:
    status: DetailedRouteStatus
    routed: tuple[NetId, ...]
    failures: tuple[NetFailure, ...]
    iterations: int
    expansions: int
    exhaustive: bool = False
    last_mile: LastMileReport | None = None

    def __post_init__(self) -> None:
        if type(self.exhaustive) is not bool:
            raise ValueError("route exhaustion marker must be boolean")
        if self.exhaustive and (
            self.status is DetailedRouteStatus.BUDGET
            or any(
                failure.kind is RouteFailureKind.BUDGET
                for failure in self.failures
            )
        ):
            raise ValueError("budget routing cannot be marked exhaustive")

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    @property
    def stranded(self) -> tuple[NetId, ...]:
        return tuple(failure.net_id for failure in self.failures)


_DECAY_FACTOR = 0.85
_PRUNE_BELOW = 1e-6
_MAX_NET_WEIGHT = 8.0
_GEOMETRIC_FAILURES = frozenset(
    {
        RouteFailureKind.DYNAMIC_ACCESS,
        RouteFailureKind.SEALED_POCKET,
        RouteFailureKind.CONGESTION_WALL,
        RouteFailureKind.COMMIT_LINK,
    }
)
_PLACEMENT_FAILURES = _GEOMETRIC_FAILURES | {RouteFailureKind.STATIC_ACCESS}


@dataclass(frozen=True, slots=True)
class FeedbackState:
    """Immutable bounded routing feedback scoped to one placement outline."""

    outline: tuple[int, int]
    net_weight: Mapping[NetId, float]
    cell_history: Mapping[Cell, float]
    logical_net_weight: Mapping[LogicalNetId, float] = field(default_factory=dict)
    endpoint_offsets: Mapping[NetId, tuple[Cell, Cell]] = field(default_factory=dict)
    #: Exact hot-wall histories keyed by the physical net whose failed search
    #: produced each wall. The shared history above remains level-specific
    #: because the global router consumes it directly; packing reads only this
    #: exact association and never forms the shared history's Cartesian product
    #: with every failed net.
    net_cell_history: Mapping[NetId, Mapping[Cell, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.outline, tuple)
            or len(self.outline) != 2
            or any(type(value) is not int or value < 0 for value in self.outline)
        ):
            raise ValueError("feedback outline must contain non-negative integer dimensions")
        width, height = self.outline
        net_weight = dict(self.net_weight)
        cell_history = dict(self.cell_history)
        logical_net_weight = dict(self.logical_net_weight)
        endpoint_offsets = dict(self.endpoint_offsets)
        net_cell_history = {
            net: dict(history)
            for net, history in self.net_cell_history.items()
        }
        if any(
            not isinstance(net, NetId)
            or not math.isfinite(value)
            or not 0.0 <= value <= _MAX_NET_WEIGHT
            for net, value in net_weight.items()
        ):
            raise ValueError("feedback net weights must be finite values from 0 to 8")
        if any(
            not isinstance(net, LogicalNetId)
            or not math.isfinite(value)
            or not 0.0 <= value <= _MAX_NET_WEIGHT
            for net, value in logical_net_weight.items()
        ):
            raise ValueError("logical feedback weights must be finite values from 0 to 8")
        if not logical_net_weight:
            for net, value in net_weight.items():
                logical_net_weight[net.logical] = max(
                    logical_net_weight.get(net.logical, 0.0),
                    value,
                )
        if any(
            not _valid_cell(cell, width, height) or not math.isfinite(value) or value < 0.0
            for cell, value in cell_history.items()
        ):
            raise ValueError(
                "feedback cell history must be finite, non-negative, and inside the outline"
            )
        if any(
            not isinstance(net, NetId)
            or any(
                not _valid_cell(cell, width, height)
                or not math.isfinite(value)
                or value < 0.0
                for cell, value in history.items()
            )
            for net, history in net_cell_history.items()
        ):
            raise ValueError(
                "per-net feedback cell history must be finite, non-negative, "
                "and inside the outline"
            )
        if any(
            not isinstance(net, NetId)
            or not isinstance(endpoints, tuple)
            or len(endpoints) != 2
            or any(not _coordinate_cell(cell) for cell in endpoints)
            for net, endpoints in endpoint_offsets.items()
        ):
            raise ValueError(
                "feedback endpoint offsets must map exact nets to two integer cells"
            )
        object.__setattr__(self, "net_weight", MappingProxyType(net_weight))
        object.__setattr__(self, "cell_history", MappingProxyType(cell_history))
        object.__setattr__(
            self,
            "logical_net_weight",
            MappingProxyType(logical_net_weight),
        )
        object.__setattr__(
            self,
            "endpoint_offsets",
            MappingProxyType(endpoint_offsets),
        )
        object.__setattr__(
            self,
            "net_cell_history",
            MappingProxyType(
                {
                    net: MappingProxyType(history)
                    for net, history in net_cell_history.items()
                }
            ),
        )

    @classmethod
    def empty(cls, outline: tuple[int, int]) -> FeedbackState:
        """Return an empty feedback snapshot for ``outline``."""
        return cls(
            outline=outline,
            net_weight={},
            cell_history={},
            logical_net_weight={},
            endpoint_offsets={},
            net_cell_history={},
        )

    def for_outline(self, outline: tuple[int, int]) -> FeedbackState:
        """Preserve logical net weights and clear spatial history on outline change."""
        if outline == self.outline:
            return self
        return FeedbackState(
            outline=outline,
            net_weight=self.net_weight,
            cell_history={},
            logical_net_weight=self.logical_net_weight,
            endpoint_offsets=self.endpoint_offsets,
            net_cell_history={},
        )


def update_feedback(
    state: FeedbackState,
    result: DetailedRouteResult,
    *,
    origins: tuple[tuple[int, int], ...] | None = None,
) -> FeedbackState:
    """Add genuine geometric failure evidence without applying stage decay."""
    geometric = tuple(failure for failure in result.failures if failure.kind in _GEOMETRIC_FAILURES)
    if not geometric:
        return state

    net_weight = dict(state.net_weight)
    logical_net_weight = dict(state.logical_net_weight)
    cell_history = dict(state.cell_history)
    endpoint_offsets = dict(state.endpoint_offsets)
    net_cell_history = {
        net: dict(history)
        for net, history in state.net_cell_history.items()
    }
    width, height = state.outline
    for failure in geometric:
        implicated = tuple(dict.fromkeys((failure.net_id, *failure.blocking_nets)))
        for net in implicated:
            logical = net.logical
            weight = min(
                _MAX_NET_WEIGHT,
                logical_net_weight.get(logical, 0.0) + 1.0,
            )
            logical_net_weight[logical] = weight
            net_weight[net] = weight
        if origins is not None:
            blocker_rows = (
                tuple(
                    (net, source, destination)
                    for net, (source, destination) in zip(
                        failure.blocking_nets,
                        failure.blocking_endpoints,
                        strict=True,
                    )
                )
                if failure.blocking_endpoints
                else ()
            )
            endpoint_rows = (
                (failure.net_id, failure.source, failure.destination),
                *blocker_rows,
            )
            for net, source, destination in endpoint_rows:
                offsets = _local_endpoint_offsets(
                    net,
                    source,
                    destination,
                    origins,
                )
                if offsets is not None:
                    endpoint_offsets[net] = offsets
        wall = tuple(
            cell
            for cell in failure.wall
            if _valid_cell(cell, width, height)
        )
        for cell in wall:
            cell_history[cell] = cell_history.get(cell, 0.0) + 1.0
        history = net_cell_history.setdefault(failure.net_id, {})
        for cell in wall:
            history[cell] = history.get(cell, 0.0) + 1.0
    return FeedbackState(
        state.outline,
        net_weight,
        cell_history,
        logical_net_weight,
        endpoint_offsets,
        net_cell_history=net_cell_history,
    )


def decay_feedback(state: FeedbackState) -> FeedbackState:
    """Apply exactly one stage-boundary decay and remove negligible values."""
    net_weight = {
        net: decayed
        for net, value in state.net_weight.items()
        if (decayed := value * _DECAY_FACTOR) >= _PRUNE_BELOW
    }
    logical_net_weight = {
        net: decayed
        for net, value in state.logical_net_weight.items()
        if (decayed := value * _DECAY_FACTOR) >= _PRUNE_BELOW
    }
    cell_history = {
        cell: decayed
        for cell, value in state.cell_history.items()
        if (decayed := value * _DECAY_FACTOR) >= _PRUNE_BELOW
    }
    net_cell_history = {
        net: {
            cell: decayed
            for cell, value in history.items()
            if (decayed := value * _DECAY_FACTOR) >= _PRUNE_BELOW
        }
        for net, history in state.net_cell_history.items()
        if net in net_weight
    }
    return FeedbackState(
        state.outline,
        net_weight,
        cell_history,
        logical_net_weight,
        {
            net: endpoints
            for net, endpoints in state.endpoint_offsets.items()
            if net in net_weight
        },
        net_cell_history=net_cell_history,
    )


def remap_feedback_nets(
    state: FeedbackState,
    nets: tuple[NetId, ...],
    *,
    outline: tuple[int, int] | None = None,
) -> FeedbackState:
    """Broadcast logical criticality onto current physical nets after rebuilding."""
    if not isinstance(nets, tuple) or any(not isinstance(net, NetId) for net in nets):
        raise ValueError("feedback remapping requires an immutable physical net tuple")
    target_outline = state.outline if outline is None else outline
    physical = {
        net: weight
        for net in nets
        if (weight := state.logical_net_weight.get(net.logical, 0.0)) >= _PRUNE_BELOW
    }
    return FeedbackState(
        target_outline,
        physical,
        {},
        state.logical_net_weight,
        {
            net: endpoints
            for net, endpoints in state.endpoint_offsets.items()
            if net in physical
        },
        net_cell_history={},
    )


def _local_endpoint_offsets(
    net: NetId,
    source: Cell | None,
    destination: Cell | None,
    origins: tuple[tuple[int, int], ...],
) -> tuple[Cell, Cell] | None:
    """Translate one exact internal net's absolute ports into strip-local cells."""
    if (
        source is None
        or destination is None
        or net.source_strip is None
        or net.destination_strip is None
        or not 0 <= net.source_strip < len(origins)
        or not 0 <= net.destination_strip < len(origins)
    ):
        return None
    source_origin = origins[net.source_strip]
    destination_origin = origins[net.destination_strip]
    return (
        (
            source[0] - source_origin[0],
            source[1] - source_origin[1],
            source[2],
        ),
        (
            destination[0] - destination_origin[0],
            destination[1] - destination_origin[1],
            destination[2],
        ),
    )


def geometric_failure_instances(
    result: DetailedRouteResult,
    instance_count: int,
) -> frozenset[int]:
    """Return exact physical endpoints implicated by current geometric failures."""
    if type(instance_count) is not int or instance_count < 0:
        raise ValueError("instance count must be a non-negative integer")
    implicated: set[int] = set()
    for failure in result.failures:
        if failure.kind not in _PLACEMENT_FAILURES:
            continue
        _add_net_endpoints(implicated, failure.net_id, instance_count)
        for blocker in failure.blocking_nets:
            _add_net_endpoints(implicated, blocker, instance_count)
    return frozenset(implicated)


def select_split_candidate(
    result: DetailedRouteResult,
    instances: tuple[StripInstanceId, ...],
    *,
    stagnation: int,
    split_after: int,
) -> int | None:
    """Select one implicated multi-machine instance after focused stagnation."""
    if type(stagnation) is not int or stagnation < 0:
        raise ValueError("split stagnation must be a non-negative integer")
    if type(split_after) is not int or split_after <= 0:
        raise ValueError("split threshold must be a positive integer")
    if not isinstance(instances, tuple):
        raise ValueError("split candidates must be an immutable instance tuple")
    if stagnation < split_after:
        return None
    implicated = geometric_failure_instances(result, len(instances))
    candidates = [index for index in implicated if instances[index].machine_count > 1]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda index: (
            -instances[index].machine_count,
            instances[index].family_id,
            instances[index].machine_start,
            index,
        ),
    )


def feedback_cost_context(
    state: FeedbackState,
    problem: PlacementProblem,
    direct_targets: tuple[DirectInsertTarget, ...] = (),
) -> PlacementCostContext:
    """Build immutable candidate-independent feedback scoring inputs."""
    if problem.logical_net_ids:
        net_weights = tuple(
            1.0 + state.logical_net_weight.get(logical, 0.0) for logical in problem.logical_net_ids
        )
    else:
        weight_by_endpoints: dict[tuple[int, int], float] = {}
        for net, weight in state.net_weight.items():
            if net.source_strip is None or net.destination_strip is None:
                continue
            endpoints = (net.source_strip, net.destination_strip)
            weight_by_endpoints[endpoints] = weight_by_endpoints.get(endpoints, 0.0) + weight
        net_weights = tuple(
            1.0 + weight_by_endpoints.get(endpoints, 0.0) for endpoints in problem.nets
        )

    return PlacementCostContext(
        net_weights=net_weights,
        net_pairs=problem.nets,
        history_outline=state.outline,
        history_summed_area=_summed_area_table(state),
        direct_targets=direct_targets,
    )


def select_lns_neighbourhood(
    result: DetailedRouteResult,
    pair: SequencePair,
    gaps: GapProfile,
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    *,
    stagnation: int = 0,
    grow_after: int = 2,
) -> frozenset[int]:
    """Select failure endpoints, neighbours, and gap strips crossing hot boxes."""
    if (
        len(pair.positive) != problem.size
        or len(gaps.east) != problem.size
        or len(decoded.x) != problem.size
    ):
        raise ValueError("LNS placement inputs must have matching sizes")
    if type(stagnation) is not int or stagnation < 0:
        raise ValueError("LNS stagnation must be a non-negative integer")
    if type(grow_after) is not int or grow_after <= 0:
        raise ValueError("LNS growth interval must be a positive integer")

    failures = tuple(
        failure for failure in result.failures if failure.kind in _PLACEMENT_FAILURES
    )
    if not failures:
        return frozenset()

    endpoints: set[int] = set()
    hot_boxes: list[tuple[int, int, int, int]] = []
    for failure in failures:
        _add_net_endpoints(endpoints, failure.net_id, problem.size)
        for blocking_net in failure.blocking_nets:
            _add_net_endpoints(endpoints, blocking_net, problem.size)
        if failure.wall:
            hot_boxes.append(
                (
                    min(cell[0] for cell in failure.wall),
                    min(cell[1] for cell in failure.wall),
                    max(cell[0] for cell in failure.wall) + 1,
                    max(cell[1] for cell in failure.wall) + 1,
                )
            )

    neighbourhood = endpoints | _sequence_neighbours(pair, endpoints)
    for strip, ((strip_width, strip_height), east, north) in enumerate(
        zip(problem.sizes, gaps.east, gaps.north, strict=True)
    ):
        x = decoded.x[strip]
        y = decoded.y[strip]
        if east and any(
            _rectangles_intersect(
                (x + strip_width, y, x + strip_width + east, y + strip_height),
                hot_box,
            )
            for hot_box in hot_boxes
        ):
            neighbourhood.add(strip)
        if north and any(
            _rectangles_intersect(
                (x, y + strip_height, x + strip_width, y + strip_height + north),
                hot_box,
            )
            for hot_box in hot_boxes
        ):
            neighbourhood.add(strip)

    if stagnation >= grow_after:
        neighbourhood.update(_sequence_neighbours(pair, neighbourhood))
    return frozenset(neighbourhood)


def _coordinate_cell(cell: object) -> bool:
    return (
        isinstance(cell, tuple)
        and len(cell) == 3
        and all(type(value) is int for value in cell)
    )


def _valid_cell(cell: object, width: int, height: int) -> bool:
    return (
        isinstance(cell, tuple)
        and len(cell) == 3
        and all(type(value) is int for value in cell)
        and 0 <= cell[0] < width
        and 0 <= cell[1] < height
        and cell[2] >= 0
    )


def _summed_area_table(state: FeedbackState) -> tuple[float, ...]:
    width, height = state.outline
    stride = width + 1
    table = [0.0] * (stride * (height + 1))
    for (x, y, _level), value in state.cell_history.items():
        table[(y + 1) * stride + x + 1] += value
    for y in range(1, height + 1):
        row = y * stride
        prior_row = (y - 1) * stride
        running = 0.0
        for x in range(1, width + 1):
            running += table[row + x]
            table[row + x] = running + table[prior_row + x]
    return tuple(table)


def _add_net_endpoints(strips: set[int], net: NetId, size: int) -> None:
    for endpoint in (net.source_strip, net.destination_strip):
        if endpoint is not None and 0 <= endpoint < size:
            strips.add(endpoint)


def _sequence_neighbours(pair: SequencePair, strips: set[int]) -> set[int]:
    neighbours: set[int] = set()
    for permutation in (pair.positive, pair.negative):
        positions = {strip: index for index, strip in enumerate(permutation)}
        for strip in strips:
            position = positions[strip]
            if position:
                neighbours.add(permutation[position - 1])
            if position + 1 < len(permutation):
                neighbours.add(permutation[position + 1])
    return neighbours


def _rectangles_intersect(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> bool:
    return (
        first[0] < second[2]
        and second[0] < first[2]
        and first[1] < second[3]
        and second[1] < first[3]
    )
