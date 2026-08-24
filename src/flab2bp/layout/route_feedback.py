from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from .sequence_pair import (
    DecodedPlacement,
    GapProfile,
    PlacementCostContext,
    PlacementProblem,
    SequencePair,
)

Cell = tuple[int, int, int]


class NetRole(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    PROLIFERATOR = "proliferator"


@dataclass(frozen=True, order=True, slots=True)
class NetId:
    source_strip: int | None
    destination_strip: int | None
    item: str
    role: NetRole
    ordinal: int


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


@dataclass(frozen=True, slots=True)
class DetailedRouteResult:
    status: DetailedRouteStatus
    routed: tuple[NetId, ...]
    failures: tuple[NetFailure, ...]
    iterations: int
    expansions: int

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


@dataclass(frozen=True, slots=True)
class FeedbackState:
    """Immutable bounded routing feedback scoped to one placement outline."""

    outline: tuple[int, int]
    net_weight: Mapping[NetId, float]
    cell_history: Mapping[Cell, float]

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
        if any(
            not isinstance(net, NetId)
            or not math.isfinite(value)
            or not 0.0 <= value <= _MAX_NET_WEIGHT
            for net, value in net_weight.items()
        ):
            raise ValueError("feedback net weights must be finite values from 0 to 8")
        if any(
            not _valid_cell(cell, width, height)
            or not math.isfinite(value)
            or value < 0.0
            for cell, value in cell_history.items()
        ):
            raise ValueError(
                "feedback cell history must be finite, non-negative, and inside the outline"
            )
        object.__setattr__(self, "net_weight", MappingProxyType(net_weight))
        object.__setattr__(self, "cell_history", MappingProxyType(cell_history))

    @classmethod
    def empty(cls, outline: tuple[int, int]) -> FeedbackState:
        """Return an empty feedback snapshot for ``outline``."""
        return cls(outline=outline, net_weight={}, cell_history={})

    def for_outline(self, outline: tuple[int, int]) -> FeedbackState:
        """Preserve logical net weights and clear spatial history on outline change."""
        if outline == self.outline:
            return self
        return FeedbackState(outline=outline, net_weight=self.net_weight, cell_history={})


def update_feedback(
    state: FeedbackState, result: DetailedRouteResult
) -> FeedbackState:
    """Add genuine geometric failure evidence without applying stage decay."""
    geometric = tuple(
        failure for failure in result.failures if failure.kind in _GEOMETRIC_FAILURES
    )
    if not geometric:
        return state

    net_weight = dict(state.net_weight)
    cell_history = dict(state.cell_history)
    width, height = state.outline
    for failure in geometric:
        net_weight[failure.net_id] = min(
            _MAX_NET_WEIGHT, net_weight.get(failure.net_id, 0.0) + 1.0
        )
        for cell in failure.wall:
            if _valid_cell(cell, width, height):
                cell_history[cell] = cell_history.get(cell, 0.0) + 1.0
    return FeedbackState(state.outline, net_weight, cell_history)


def decay_feedback(state: FeedbackState) -> FeedbackState:
    """Apply exactly one stage-boundary decay and remove negligible values."""
    net_weight = {
        net: decayed
        for net, value in state.net_weight.items()
        if (decayed := value * _DECAY_FACTOR) >= _PRUNE_BELOW
    }
    cell_history = {
        cell: decayed
        for cell, value in state.cell_history.items()
        if (decayed := value * _DECAY_FACTOR) >= _PRUNE_BELOW
    }
    return FeedbackState(state.outline, net_weight, cell_history)


def feedback_cost_context(
    state: FeedbackState,
    problem: PlacementProblem,
    decoded: DecodedPlacement,
) -> PlacementCostContext:
    """Build per-net weights and summed-area congestion-box integrals."""
    if len(decoded.x) != problem.size:
        raise ValueError("decoded placement must match the placement problem size")

    weight_by_endpoints: dict[tuple[int, int], float] = {}
    for net, weight in state.net_weight.items():
        if net.source_strip is None or net.destination_strip is None:
            continue
        endpoints = (net.source_strip, net.destination_strip)
        weight_by_endpoints[endpoints] = weight_by_endpoints.get(endpoints, 0.0) + weight

    table, stride = _summed_area_table(state)
    width, height = state.outline
    history_cost: list[float] = []
    for source, destination in problem.nets:
        source_width, source_height = problem.sizes[source]
        destination_width, destination_height = problem.sizes[destination]
        x0 = min(width, max(0, min(decoded.x[source], decoded.x[destination])))
        y0 = min(height, max(0, min(decoded.y[source], decoded.y[destination])))
        x1 = min(
            width,
            max(
                decoded.x[source] + source_width,
                decoded.x[destination] + destination_width,
            ),
        )
        y1 = min(
            height,
            max(
                decoded.y[source] + source_height,
                decoded.y[destination] + destination_height,
            ),
        )
        history_cost.append(_rectangle_sum(table, stride, x0, y0, x1, y1))

    return PlacementCostContext(
        net_weights=tuple(
            1.0 + weight_by_endpoints.get(endpoints, 0.0)
            for endpoints in problem.nets
        ),
        history_cost_by_net=tuple(history_cost),
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
        failure for failure in result.failures if failure.kind in _GEOMETRIC_FAILURES
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


def _valid_cell(cell: object, width: int, height: int) -> bool:
    return (
        isinstance(cell, tuple)
        and len(cell) == 3
        and all(type(value) is int for value in cell)
        and 0 <= cell[0] < width
        and 0 <= cell[1] < height
        and cell[2] >= 0
    )


def _summed_area_table(state: FeedbackState) -> tuple[list[float], int]:
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
    return table, stride


def _rectangle_sum(
    table: list[float],
    stride: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> float:
    return (
        table[y1 * stride + x1]
        - table[y0 * stride + x1]
        - table[y1 * stride + x0]
        + table[y0 * stride + x0]
    )


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
