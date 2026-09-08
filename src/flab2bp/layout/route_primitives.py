"""Physical single-stream connectors offered to ordinary routing searches."""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import replace
from fractions import Fraction
from functools import lru_cache
from typing import TYPE_CHECKING

from flab2bp.dsp import catalog
from flab2bp.dsp.rules import BELT_PORT_DRAW_TO_SLOT
from flab2bp.layout import junction
from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.route_feedback import Cell

if TYPE_CHECKING:
    from flab2bp.layout.routing_domain import _Canvas, _Grid

Edge = tuple[Cell, Cell]


def _translated(
    candidate: junction.SplitterRouteCandidate, dx: int, dy: int
) -> junction.SplitterRouteCandidate:
    def cell(value: Cell) -> Cell:
        return value[0] + dx, value[1] + dy, value[2]

    return replace(
        candidate,
        stack_members=tuple(
            replace(member, x=member.x + dx, y=member.y + dy) for member in candidate.stack_members
        ),
        entry=replace(candidate.entry, dock=cell(candidate.entry.dock)),
        exit=replace(candidate.exit, dock=cell(candidate.exit.dock)),
        foreign_keepout=frozenset(cell(value) for value in candidate.foreign_keepout),
    )


@lru_cache(maxsize=32)
def _templates(
    rules: catalog.BeltAltitudeRules,
) -> tuple[junction.SplitterRouteCandidate, ...]:
    # A canonical witness per directed lattice edge remains immutable across
    # reroutes and incumbent snapshots. Alternative same-edge bodies are not
    # exhaustively searched, so failure of this model is never a physical proof.
    candidates: dict[Edge, junction.SplitterRouteCandidate] = {}
    for level in range(int(rules.max_z) + 1):
        for yaw in (0.0, 90.0, 180.0, 270.0):
            for candidate in junction.splitter_route_candidates(
                0, 0, level, yaw=yaw, altitude_rules=rules, carries_item=""
            ):
                if candidate.entry.dock[2] != level:
                    continue
                candidate = _translated(
                    candidate, -candidate.entry.dock[0], -candidate.entry.dock[1]
                )
                edge = candidate.entry.dock, candidate.exit.dock
                candidates.setdefault(edge, candidate)
    return tuple(candidates.values())


@lru_cache(maxsize=32)
def _template_groups(
    rules: catalog.BeltAltitudeRules,
) -> tuple[tuple[Cell, int, dict[int, tuple[int, junction.SplitterRouteCandidate]]], ...]:
    groups: dict[Cell, dict[int, tuple[int, junction.SplitterRouteCandidate]]] = {}
    for order, template in enumerate(_templates(rules)):
        height = template.entry.dock[2]
        dx, dy, end_height = template.exit.dock
        groups.setdefault((dx, dy, end_height - height), {})[height] = order, template
    return tuple(
        (offset, sum(1 << height for height in templates), templates)
        for offset, templates in groups.items()
    )


class RoutePrimitives:
    """Retain physical witnesses independently of transient grid indices.

    Bodies never carry two unrelated streams. A witness is private to the path
    traversing its directed edge; the routing transaction claims its whole
    keepout, while emission constructs two distinct physical attachments.
    """

    def __init__(self, rules: catalog.BeltAltitudeRules) -> None:
        self.rules = rules
        self.witnesses: dict[Edge, junction.SplitterRouteCandidate] = {}

    def on_path(self, path: Sequence[Cell]) -> tuple[junction.SplitterRouteCandidate, ...]:
        return tuple(
            self.witnesses[edge]
            for edge in zip(path, path[1:], strict=False)
            if edge in self.witnesses
        )

    def guards(self, path: Sequence[Cell]) -> set[Cell]:
        return {cell for candidate in self.on_path(path) for cell in candidate.foreign_keepout}

    def selection(
        self, paths: Mapping[int, Sequence[Cell]], taps: Collection[Cell] = ()
    ) -> tuple[PlacedBuilding, ...]:
        from flab2bp.layout.routing_domain import _splitter_stack_geometry

        return (
            *(member for tap in sorted(set(taps)) for member in _splitter_stack_geometry(*tap)),
            *(
                member
                for path in paths.values()
                for candidate in self.on_path(path)
                for member in candidate.stack_members
            ),
        )

    def edges(
        self,
        canvas: _Canvas,
        grid: _Grid,
        starts: Sequence[Cell],
        goals: Collection[Cell],
        *,
        forbidden: Collection[Cell],
        excluded_edges: Collection[Edge] = (),
        active_paths: Mapping[int, tuple[Cell, ...]],
        active_taps: Collection[Cell] = (),
        deadline: float | None,
        power_allows: Callable[[PlacedBuilding], bool] | None = None,
    ) -> dict[int, tuple[tuple[int, float], ...]]:
        from flab2bp.layout.routing_domain import _building_collider_hits

        if not starts or not goals:
            return {}
        # Candidate construction is local to the endpoint envelope, not a second
        # unbounded whole-canvas solve. The full belt graph still searches every
        # technology-legal level; omitted connector sites remain inconclusive.
        endpoints = (*starts, *goals)
        x0 = max(grid.span[0], min(cell[0] for cell in endpoints) - 2)
        y0 = max(grid.span[1], min(cell[1] for cell in endpoints) - 2)
        x1 = min(grid.span[2], max(cell[0] for cell in endpoints) + 2)
        y1 = min(grid.span[3], max(cell[1] for cell in endpoints) + 2)
        forbidden_cells = frozenset(forbidden)
        committed = self.selection(active_paths, active_taps)
        if deadline is not None and time.monotonic() >= deadline:
            return {}
        groups = _template_groups(self.rules)
        # Occupancy is fixed throughout this enumeration, but reservations and
        # guards may change before the next call. Cache exact Canvas.free results
        # locally, not grid.occ: the latter also encodes search bounds and omits
        # the current net's reservation ownership.
        columns: dict[tuple[int, int], int] = {}

        def free_levels(x: int, y: int) -> int:
            column = x, y
            cached = columns.get(column)
            if cached is not None:
                return cached
            mask = 0
            for height in range(canvas.levels):
                cell = x, y, height
                if cell not in forbidden_cells and canvas.free(cell):
                    mask |= 1 << height
            columns[column] = mask
            return mask

        rows: dict[int, list[tuple[int, float]]] = {}
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                if deadline is not None and time.monotonic() >= deadline:
                    return {index: tuple(row) for index, row in rows.items()}
                start_free = free_levels(x, y)
                if not start_free:
                    continue
                available: list[tuple[int, junction.SplitterRouteCandidate]] = []
                for (dx, dy, dz), template_heights, templates in groups:
                    ex, ey = x + dx, y + dy
                    if not (
                        grid.span[0] <= ex <= grid.span[2] and grid.span[1] <= ey <= grid.span[3]
                    ):
                        continue
                    end_free = free_levels(ex, ey)
                    end_at_start = end_free >> dz if dz >= 0 else end_free << -dz
                    heights = template_heights & start_free & end_at_start
                    if not heights:
                        continue
                    if self.rules.vertical_construction:
                        # Exactly the former two corner orders at both port
                        # heights, evaluated for all levels together. Opposite
                        # ports additionally need their middle cardinal tile;
                        # parallel ports need no horizontal intermediate tile.
                        horizontal = start_free & end_free
                        if abs(dx) == 2 or abs(dy) == 2:
                            horizontal &= free_levels((x + ex) // 2, (y + ey) // 2)
                        elif dx and dy:
                            horizontal &= free_levels(x, ey) | free_levels(ex, y)
                        at_end = horizontal >> dz if dz >= 0 else horizontal << -dz
                        heights &= ~(horizontal | at_end)
                    while heights:
                        bit = heights & -heights
                        available.append(templates[bit.bit_length() - 1])
                        heights ^= bit
                # Grouping must not change edge tie order or the canonical body.
                available.sort(key=lambda value: value[0])
                for _order, template in available:
                    start = x, y, template.entry.dock[2]
                    end = (
                        x + template.exit.dock[0],
                        y + template.exit.dock[1],
                        template.exit.dock[2],
                    )
                    edge = start, end
                    if edge in excluded_edges:
                        continue
                    candidate = self.witnesses.get(edge)
                    if candidate is None:
                        candidate = _translated(template, x, y)
                    if any(
                        not free_levels(cell[0], cell[1]) & (1 << cell[2])
                        for cell in candidate.foreign_keepout
                        if 0 <= cell[2] < canvas.levels
                    ):
                        continue
                    if power_allows is not None and any(
                        not power_allows(member) for member in candidate.stack_members
                    ):
                        continue
                    if any(
                        _building_collider_hits(canvas.buildings, member)
                        for member in candidate.stack_members
                    ):
                        continue
                    if not canvas.projected_buildings_are_clear(
                        candidate.stack_members, selected=committed, deadline=deadline
                    ):
                        continue
                    self.witnesses.setdefault(edge, candidate)
                    distance = abs(end[0] - start[0]) + abs(end[1] - start[1])
                    cost = float(
                        distance + abs(end[2] - start[2]) + 4 * len(candidate.stack_members)
                    )
                    rows.setdefault(grid.index(start), []).append((grid.index(end), cost))
        return {index: tuple(row) for index, row in rows.items()}

    def altitudes(self, path: Sequence[Cell], *, ramped: bool) -> list[Fraction] | None:
        from flab2bp.layout.routing_domain import _altitude_profile

        result: list[Fraction] = []
        start = 0
        for at in range(len(path)):
            if at == len(path) - 1 or (path[at], path[at + 1]) in self.witnesses:
                part = _altitude_profile(path[start : at + 1], ramped=ramped)
                if part is None:
                    return None
                result.extend(part)
                start = at + 1
        return result

    def path_is_clear(self, path: Sequence[Cell]) -> bool:
        cells = set(path)
        selected = self.on_path(path)
        for at, candidate in enumerate(selected):
            excused = {candidate.entry.dock, candidate.exit.dock}
            if (candidate.foreign_keepout & cells) - excused:
                return False
            for earlier in selected[:at]:
                if candidate.foreign_keepout & earlier.foreign_keepout:
                    return False
        return True

    def emit(
        self,
        canvas: _Canvas,
        candidate: junction.SplitterRouteCandidate,
        source: int,
        target: int,
        belt_id: int,
        belt_model: int,
        item: str,
    ) -> None:
        first = len(canvas.buildings)
        for offset, member in enumerate(candidate.stack_members):
            canvas.add(
                replace(
                    member,
                    carries_item=item if offset == len(candidate.stack_members) - 1 else None,
                    input_obj=None if member.input_obj is None else first + member.input_obj,
                ),
                solid=False,
            )
        top = first + len(candidate.stack_members) - 1
        anchor = candidate.stack_members[-1]
        # Separate records are essential even for coplanar ports: their real
        # positions come from different prefab poses during blueprint encoding.
        incoming = canvas.add(
            PlacedBuilding(
                item_id=belt_id,
                model_index=belt_model,
                x=anchor.x,
                y=anchor.y,
                z=Fraction(candidate.entry.dock[2]),
                width=1,
                height=1,
                carries_item=item,
                output_obj=top,
                output_to_slot=candidate.entry.slot,
            )
        )
        outgoing = canvas.add(
            PlacedBuilding(
                item_id=belt_id,
                model_index=belt_model,
                x=anchor.x,
                y=anchor.y,
                z=Fraction(candidate.exit.dock[2]),
                width=1,
                height=1,
                carries_item=item,
                input_obj=top,
                input_from_slot=candidate.exit.slot,
                input_to_slot=BELT_PORT_DRAW_TO_SLOT,
                output_obj=target,
            )
        )
        canvas.buildings[source] = replace(canvas.buildings[source], output_obj=incoming)
        # The outgoing attachment owns the incoming physical edge to target.
        canvas.buildings[target] = replace(canvas.buildings[target], input_obj=outgoing)
        # Search guards were released before commit. As with source taps, the
        # entire physical stack stays guarded for all later routing passes;
        # its selected docks are already occupied by this stream's own belts.
        canvas.guard.update(candidate.foreign_keepout)
