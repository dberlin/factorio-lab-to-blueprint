"""Bridge the real strip/interface emitter to bounded complete-path selection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from typing import override

from flab2bp.dsp import catalog
from flab2bp.layout import routing_domain as rd
from flab2bp.spec import BuildSpec

from .allocation import Order
from .budget import TransportRefusal, WorkBudget
from .flights import ReusingConstructor
from .paths import Endpoint, FixedPath, Obligation, TemplateProblem
from .solver import SolveStats, select

Cell = tuple[int, int, int]


@dataclass(frozen=True)
class RoutingRun:
    budget: WorkBudget
    order: Order = "captured"
    solve_stats: SolveStats = field(default_factory=SolveStats)
    checkpoint: Callable[[str], None] | None = None


class TemplateConstructor(ReusingConstructor):
    def __init__(
        self, spec: BuildSpec, rules: catalog.BeltAltitudeRules, session: RoutingRun
    ) -> None:
        super().__init__(spec, rules)
        self.session = session
        self.x_tracks: tuple[int, ...] = ()
        self.y_tracks: tuple[int, ...] = ()
        self.selected_points: dict[int, tuple[Cell, ...]] = {}
        self.selection_complete = False
        self.problem: TemplateProblem | None = None

    def set_tracks(self, x_tracks: tuple[int, ...], y_tracks: tuple[int, ...]) -> None:
        self.x_tracks = x_tracks
        self.y_tracks = y_tracks

    def endpoint(self, port: rd._Port, outward: tuple[int, int]) -> Endpoint:
        building = self.canvas.buildings[port.belt]
        if (
            not catalog.is_belt(building.item_id)
            or building.x != port.x
            or building.y != port.y
            or building.z != port.z
        ):
            raise TransportRefusal("PHYSICAL_ACCESS_CONFLICT", "attachment is not its actual belt")
        node = next(
            (
                index
                for index in (building.input_obj, building.output_obj)
                if index in self.junctions
            ),
            None,
        )
        return Endpoint((port.x, port.y, port.z), outward, port.belt, node)

    def _owns_blocked_endpoint(self, endpoint: Endpoint) -> bool:
        owner = self.canvas.blocked.get(endpoint.cell)
        if owner == endpoint.port_id:
            return True
        node = endpoint.junction_id
        if owner is None or node is None:
            return False
        junction = self.canvas.buildings[node]
        other = self.canvas.buildings[owner]
        # The occupancy map stores only the last of a splitter's co-located
        # attachment belts. Verify actual incidence, not coordinate coincidence.
        return (
            junction.x == endpoint.cell[0]
            and junction.y == endpoint.cell[1]
            and junction.z == endpoint.cell[2]
            and other.x == endpoint.cell[0]
            and other.y == endpoint.cell[1]
            and other.z == endpoint.cell[2]
            and catalog.is_belt(other.item_id)
            and node in (other.input_obj, other.output_obj)
        )

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
        self.session.budget.check()
        self.session.budget.charge(
            "audit_cells",
            sum(
                sum(abs(a - b) for a, b in zip(first, second, strict=True))
                for first, second in zip(points, points[1:], strict=False)
            )
            + 1,
        )
        super().connect(source, sink, points, item, rate, role)

    def _fixed_path(self, index: int) -> FixedPath:
        link = self.links[index]
        points = link.cells

        def terminal(belt: int, cell: Cell, neighbour: Cell) -> Endpoint:
            dx, dy = neighbour[0] - cell[0], neighbour[1] - cell[1]
            outward = ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))
            return self.endpoint(rd._Port(belt, *cell[:2], z=cell[2]), outward)

        return FixedPath(
            points,
            terminal(link.source, points[0], points[1]),
            terminal(link.sink, points[-1], points[-2]),
            link.item,
        )

    def finish(self) -> None:
        budget = self.session.budget
        budget.check()
        # These are fixed interface transfers, not speculative global paths.
        for flight in self.pending:
            if flight.role in ("local-source", "local-sink"):
                if flight.exclusive_level >= self.canvas.levels:
                    raise TransportRefusal(
                        "PHYSICAL_ACCESS_CONFLICT", "local transfer exceeds original altitude"
                    )
                self.connect(
                    flight.source.port,
                    flight.sink.port,
                    flight.points(flight.exclusive_level),
                    flight.item,
                    flight.rate,
                    flight.role,
                )
        global_flights = [
            (index, flight)
            for index, flight in enumerate(self.pending)
            if flight.role not in ("local-source", "local-sink")
        ]
        fixed_belts: set[int] = set()
        for link in self.links:
            current = link.source
            visited: set[int] = set()
            while current not in visited:
                visited.add(current)
                fixed_belts.add(current)
                if current == link.sink:
                    break
                onward = self.canvas.buildings[current].output_obj
                if onward is None:
                    raise TransportRefusal("PHYSICAL_ACCESS_CONFLICT", "fixed link is disconnected")
                current = onward
            else:
                raise TransportRefusal("PHYSICAL_ACCESS_CONFLICT", "fixed link has a cycle")
        blocked = {cell for cell, owner in self.canvas.blocked.items() if owner not in fixed_belts}
        blocked.update(self.canvas.guard)
        for (x, y), levels in self.canvas.belt_ban.items():
            blocked.update((x, y, z) for z in levels)
        for x, y in self.canvas.keep_out:
            blocked.update((x, y, z) for z in range(self.canvas.levels))
        blocked.update(
            cell
            for cell, port in self.canvas.reserved.items()
            if port not in self.canvas.routing_ports
        )
        fixed_paths = tuple(self._fixed_path(i) for i in range(len(self.links)))
        extent = set(self.canvas.blocked) | blocked
        extent.update(cell for path in fixed_paths for cell in path.points)
        xs = [cell[0] for cell in extent]
        ys = [cell[1] for cell in extent]
        x_tracks = tuple(sorted(set(self.x_tracks) | {min(xs) - 8, max(xs) + 8}))
        y_tracks = tuple(sorted(set(self.y_tracks) | {min(ys) - 8, max(ys) + 8}))
        self.problem = TemplateProblem(
            tuple(
                Obligation(
                    index,
                    flight.item,
                    flight.rate,
                    self.endpoint(flight.source.port, flight.source.outward),
                    self.endpoint(flight.sink.port, flight.sink.outward),
                )
                for index, flight in global_flights
            ),
            frozenset(blocked),
            fixed_paths,
            x_tracks,
            y_tracks,
            tuple(range(3, self.canvas.levels)),
        )
        attachment_paths: tuple[Obligation | FixedPath, ...] = (
            *self.problem.obligations,
            *fixed_paths,
        )
        endpoints = tuple(
            endpoint
            for path in attachment_paths
            for endpoint in (path.source, path.sink)
            if self._owns_blocked_endpoint(endpoint)
            and endpoint.cell not in self.canvas.guard
            and endpoint.cell[2] not in self.canvas.belt_ban.get(endpoint.cell[:2], ())
            and endpoint.cell[:2] not in self.canvas.keep_out
            and self.canvas.reserved.get(endpoint.cell, endpoint.cell) == endpoint.cell
        )
        self.problem = TemplateProblem(
            self.problem.obligations,
            self.problem.blocked,
            fixed_paths,
            x_tracks,
            y_tracks,
            self.problem.levels,
            endpoints,
        )
        self.selected_points = select(
            self.problem, budget, self.session.solve_stats, self.session.checkpoint
        )
        self.selection_complete = True
        for index, flight in global_flights:
            budget.check()
            points = self.selected_points[index]
            self.connect(
                flight.source.port,
                flight.sink.port,
                list(points),
                flight.item,
                flight.rate,
                flight.role,
            )
        budget.check()
