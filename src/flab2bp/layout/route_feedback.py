from dataclasses import dataclass
from enum import StrEnum

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
