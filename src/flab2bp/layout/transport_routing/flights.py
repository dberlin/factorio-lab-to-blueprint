"""Buffer rated flights while reserving every emitted fixed link."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import override

from flab2bp.dsp import catalog
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.route_feedback import Cell
from flab2bp.spec import BuildSpec

from .construction import ConstructionRefusal, Constructor, Terminal, path_through


def occupied_cells(path: tuple[Cell, ...]) -> set[Cell]:
    """Include every height crossed by an emitted direct vertical link."""
    cells = set(path)
    for a, b in zip(path, path[1:], strict=False):
        if a[:2] == b[:2] and a[2] != b[2]:
            cells.update((a[0], a[1], z) for z in range(min(a[2], b[2]), max(a[2], b[2]) + 1))
    return cells


@dataclass(frozen=True)
class Flight:
    source: Terminal
    sink: Terminal
    item: str
    rate: Fraction
    exclusive_level: int
    middle_x: int
    role: str

    def points(self, level: int) -> list[Cell]:
        reverse = self.role == "local-sink"
        source, sink = (self.sink, self.source) if reverse else (self.source, self.sink)
        a, b = source.port, sink.port
        local = self.role in ("local-source", "local-sink")
        launch = 2 * self.exclusive_level if local else 2
        ax, ay = a.x + launch * source.outward[0], a.y + launch * source.outward[1]
        bx, by = b.x + 2 * sink.outward[0], b.y + 2 * sink.outward[1]
        # Input lanes may begin at the machine edge; stay two cells west of it.
        # Ascending sink ranks terminate beyond the lower-ranked collector trees.
        middle_x = a.x - 2 if local and self.exclusive_level > 1 else self.middle_x
        points = [
            (a.x, a.y, a.z),
            (ax, ay, a.z),
            (ax, ay, level),
            (middle_x, ay, level),
            (middle_x, by, level),
            (bx, by, level),
            (bx, by, b.z),
            (b.x, b.y, b.z),
        ]
        if reverse:
            points.reverse()
        return points


class ReusingConstructor(Constructor):
    def __init__(self, spec: BuildSpec, rules: catalog.BeltAltitudeRules) -> None:
        super().__init__(spec, rules)
        self.occupied: set[Cell] = set()
        self.pending: list[Flight] = []

    @override
    def connect(
        self,
        source: rd._Port,
        sink: rd._Port,
        points: list[Cell],
        item: str,
        rate: Fraction,
        role: str,
    ) -> None:
        path = path_through(points)
        full = occupied_cells(path) - {path[0], path[-1]}
        blocked = full & self.occupied
        if blocked:
            raise ConstructionRefusal(f"constructed paths intersect: {item} at {min(blocked)}")
        if len(path) != len(set(path)):
            raise ConstructionRefusal(f"fixed path retraces itself: {item}")
        for cell in sorted(full):
            if not self.canvas.free(cell):
                raise ConstructionRefusal(
                    f"constructed path meets fixed geometry: {item} at {cell}"
                )
        super().connect(source, sink, points, item, rate, role)
        self.occupied.update(occupied_cells(path))

    @override
    def flight(
        self,
        source: Terminal,
        sink: Terminal,
        item: str,
        rate: Fraction,
        level: int,
        middle_x: int,
        role: str,
    ) -> None:
        self.pending.append(Flight(source, sink, item, rate, level, middle_x, role))
