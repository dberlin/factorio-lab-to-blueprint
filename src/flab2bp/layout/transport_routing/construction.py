"""Emit exact splitter interfaces and guarded orthogonal belt links."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache

from flab2bp.dsp import catalog, colliders
from flab2bp.layout import junction
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.route_feedback import Cell
from flab2bp.spec import BuildSpec


@lru_cache(maxsize=128)
def spherical_overflight_limit(model_index: int, z: Fraction) -> int:
    """First lattice plane above every projected collider corner.

    A flat top is insufficient near an integer plane: a corner has greater
    planetary radius than the collider's centre. Radial extent is invariant
    under latitude and yaw, so this sufficient clearance needs no frame guess
    or arbitrary padding. Target colliders inherit the preview rotation and
    ignore their stored local quaternion, exactly as `target_boxes` does.
    """
    boxes = colliders.build_colliders(model_index)
    if not boxes:
        return math.floor(z) + 1
    position, _ = colliders.preview_pose(0.0, 0.0, float(z), 0.0)
    base_radius = math.hypot(*position)
    outer_radius = max(
        math.hypot(
            abs(centre[0]) + half[0],
            abs(base_radius + centre[1]) + half[1],
            abs(centre[2]) + half[2],
        )
        for centre, half, _ in boxes
    )
    bound = float(z) + (
        outer_radius - base_radius + colliders.BELT_PROBE_RADIUS - colliders.BELT_PROBE_LIFT
    ) * float(catalog.BELT_Z_PER_WORLD_UNIT)
    return math.floor(bound) + 1


@dataclass(frozen=True)
class Terminal:
    port: rd._Port
    outward: tuple[int, int]


@dataclass(frozen=True)
class ConstructedLink:
    item: str
    source: int
    sink: int
    rate: Fraction
    cells: tuple[Cell, ...]
    role: str


class ConstructionRefusal(ValueError):
    pass


def path_through(points: list[Cell]) -> tuple[Cell, ...]:
    cells = [points[0]]
    for end in points[1:]:
        x, y, z = cells[-1]
        ex, ey, ez = end
        if sum((x != ex, y != ey, z != ez)) > 1:
            raise ConstructionRefusal(f"non-orthogonal planned segment: {cells[-1]} -> {end}")
        if z != ez:
            cells.append(end)
        elif x != ex:
            step = 1 if ex > x else -1
            cells.extend((xx, y, z) for xx in range(x + step, ex + step, step))
        elif y != ey:
            step = 1 if ey > y else -1
            cells.extend((x, yy, z) for yy in range(y + step, ey + step, step))
    return tuple(cells)


class Constructor:
    def __init__(self, spec: BuildSpec, rules: catalog.BeltAltitudeRules) -> None:
        self.spec = spec
        self.canvas = rd._Canvas(
            belt_rules=rules,
            sorter_tiers=rd._sorter_tiers_for(spec),
            sorter_stacks=rd._sorter_stacks_for(spec),
            lane_stacks=rd._lane_stacks_for(spec),
            power_building=catalog.power_tower_building(spec.power_tower_item_id),
        )
        self.belt_id = catalog.get_item_id(spec.belt_item_id) or 2001
        self.belt_model = catalog.building(self.belt_id).model_index
        self.links: list[ConstructedLink] = []
        self.junctions: list[int] = []

    def belt(self, cell: Cell, item: str) -> rd._Port:
        if not self.canvas.free(cell):
            raise ConstructionRefusal(f"fixed belt cell is occupied: {item} at {cell}")
        x, y, z = cell
        index = self.canvas.add(
            rd.PlacedBuilding(
                item_id=self.belt_id,
                model_index=self.belt_model,
                x=x,
                y=y,
                z=Fraction(z),
                width=1,
                height=1,
                carries_item=item,
            ),
            level=z,
        )
        return rd._Port(index, x, y, z=z)

    def connect(
        self,
        source: rd._Port,
        sink: rd._Port,
        points: list[Cell],
        item: str,
        rate: Fraction,
        role: str,
    ) -> None:
        cells = path_through(points)
        assert cells[0] == (source.x, source.y, source.z)
        assert cells[-1] == (sink.x, sink.y, sink.z)
        if self.canvas.buildings[source.belt].output_obj is not None:
            raise ConstructionRefusal(f"source {source.belt} needs a physical splitter")
        indices = [source.belt]
        indices.extend(self.belt(cell, item).belt for cell in cells[1:-1])
        indices.append(sink.belt)
        for left, right in zip(indices, indices[1:], strict=False):
            self.canvas.buildings[left] = rd._relink(self.canvas.buildings[left], output_obj=right)
        self.links.append(ConstructedLink(item, source.belt, sink.belt, rate, cells, role))

    def splitter(self, x: int, y: int, item: str) -> int:
        node = junction.make_splitter(x, y, carries_item=item)
        if not junction.site_is_clear(self.canvas.buildings, x, y):
            raise ConstructionRefusal(f"fixed splitter seat is occupied: {item} at {(x, y)}")
        index = self.canvas.add(node)
        self.junctions.append(index)
        return index

    def dock(self, index: int, direction: tuple[int, int], *, feed: bool) -> Terminal:
        node = self.canvas.buildings[index]
        assert any(
            port.dock == (*direction, 0)
            for port in junction._route_ports(node.model_index, node.yaw)
        )
        # Game attachment records are colocated stubs, not the adjacent lattice
        # docks used by route queries. Canonical slot binding emits port poses.
        stub = self.canvas.add(
            rd.PlacedBuilding(
                item_id=self.belt_id,
                model_index=self.belt_model,
                x=node.x,
                y=node.y,
                z=node.z,
                width=1,
                height=1,
                carries_item=node.carries_item,
            )
        )
        port = rd._Port(stub, int(node.x), int(node.y), z=int(node.z))
        self.canvas.buildings[port.belt] = (
            junction.attach_input(self.canvas.buildings[port.belt], index)
            if feed
            else junction.attach_output(self.canvas.buildings[port.belt], index)
        )
        return Terminal(port, direction)

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
        if level >= self.canvas.levels:
            raise ConstructionRefusal("fixed flight allocation exceeds original technology")
        a, b = source.port, sink.port
        ax, ay = a.x + 2 * source.outward[0], a.y + 2 * source.outward[1]
        bx, by = b.x + 2 * sink.outward[0], b.y + 2 * sink.outward[1]
        self.connect(
            a,
            b,
            [
                (a.x, a.y, a.z),
                (ax, ay, a.z),
                (ax, ay, level),
                (middle_x, ay, level),
                (middle_x, by, level),
                (bx, by, level),
                (bx, by, b.z),
                (b.x, b.y, b.z),
            ],
            item,
            rate,
            role,
        )
