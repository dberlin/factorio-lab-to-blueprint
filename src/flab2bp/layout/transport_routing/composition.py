"""Construct complete physical transport from exact strip obligations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout import finalize
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.band_policy import BAND_DIMENSIONS, BandPolicy
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.slots import assign_sorter_slots
from flab2bp.layout.strip_variants import CargoDomain
from flab2bp.spec import BuildSpec

from . import junctions
from .allocation import external_roots, select_topology
from .budget import WorkBudget
from .construction import ConstructionRefusal, Constructor, Terminal
from .flights import Flight
from .inventory import Inventory, TransportDemand, prepare_inventory
from .routing import RoutingRun, TemplateConstructor

# Two facing two-cell terminal approaches need distinct riser columns.
_BOUNDARY_CLEARANCE = 2 + 1 + 2


def _tree_rows(
    inventory: Inventory,
    families: dict[int, list[TransportDemand]],
    strip_belts: dict[int, list[int]],
    nodes: dict[int, list[int]],
    side: int,
    budget: WorkBudget,
) -> dict[int, int]:
    """Seat complete trees beside a module when their fixed access fits there."""
    rows: dict[int, int] = {}
    for strip, belts in nodes.items():
        module = inventory.modules[strip]
        next_row = 2
        for belt in belts:
            endpoint = families[belt][0].source if side > 0 else families[belt][0].sink
            assert endpoint is not None
            extent = junctions.tree_extent(len(families[belt]))
            x = endpoint.x + 4 * side
            beside = x - 2 >= module.width if side > 0 else x + 2 < 0
            row = max(next_row, 2 if beside else module.height + 2)
            other_rows = []
            for other in strip_belts[strip]:
                if other == belt:
                    continue
                port = families[other][0].source if side > 0 else families[other][0].sink
                assert port is not None
                other_rows.append(port.y)
            while True:
                budget.check()
                # Reserve every directed dock, including unused ones, and the
                # ranked ground approaches on this side of the module.
                if not any(row - 2 <= y <= row + extent - 4 for y in other_rows) and not (
                    row <= endpoint.y <= row + extent - 6
                ):
                    break
                row += 1
            rows[belt] = row
            next_row = row + extent
    return rows


def _sink_terminals(
    constructor: Constructor,
    sink_families: dict[int, list[TransportDemand]],
    physical: dict[int, rd._Port],
    rates: dict[int, Fraction],
    origins: dict[int, tuple[int, int]],
    sink_access: dict[int, int],
    node_rows: dict[int, int],
) -> dict[int, Terminal]:
    sinks: dict[int, Terminal] = {}
    for belt, family in sink_families.items():
        port = physical[belt]
        if len(family) == 1:
            distance = 2 * sink_access[belt] if family[0].role == "local-coating" else 0
            if distance:
                terminal = constructor.belt((port.x - distance, port.y, port.z), family[0].item)
                constructor.connect(
                    terminal,
                    port,
                    [(terminal.x, terminal.y, terminal.z), (port.x, port.y, port.z)],
                    family[0].item,
                    rates[family[0].ordinal],
                    "local-sink-access",
                )
                port = terminal
            sinks[family[0].ordinal] = Terminal(port, (-1, 0))
            continue
        endpoint = family[0].sink
        assert endpoint is not None
        node = constructor.splitter(
            port.x - 4,
            origins[endpoint.strip][1] + node_rows[belt],
            family[0].item,
        )
        outlet = constructor.dock(node, (1, 0), feed=False)
        constructor.flight(
            outlet,
            Terminal(port, (-1, 0)),
            family[0].item,
            sum((rates[d.ordinal] for d in family), Fraction()),
            1 + sink_access[belt],
            port.x - 2 - 2 * sink_access[belt],
            "local-sink",
        )
        leaves = junctions.terminals(
            constructor, node, [rates[d.ordinal] for d in family], feed=True
        )
        sinks.update(((d.ordinal, leaf) for d, leaf in zip(family, leaves, strict=True)))
    return sinks


@dataclass(frozen=True, slots=True)
class ProliferatorBanks:
    nodes: tuple[tuple[tuple[int, int], ...], ...]
    bounds: tuple[int, int, int, int] | None


def plan_proliferator_banks(inventory: Inventory, height: int) -> ProliferatorBanks:
    """Exact relative supply-node layout, including two-cell terminal approaches."""
    rows = max(2, (height - 8) // 6)
    x = 0
    groups: list[tuple[tuple[int, int], ...]] = []
    occupied: list[tuple[int, int]] = []
    for supply in inventory.supplies:
        count = len(supply.coatings) // 2
        positions = tuple(
            (
                x - 10 * (index // rows),
                6 * (index % rows if (index // rows) % 2 == 0 else rows - 1 - index % rows),
            )
            for index in range(count)
        )
        groups.append(positions)
        occupied.extend(positions)
        if positions:
            x -= 10 * ((count + rows - 1) // rows) + 6
    bounds = (
        (
            min(x for x, _ in occupied) - 2,
            -2,
            2,
            max(y for _, y in occupied) + 2,
        )
        if occupied
        else None
    )
    return ProliferatorBanks(tuple(groups), bounds)


def _proliferator_terminals(
    constructor: Constructor, inventory: Inventory, height: int
) -> tuple[dict[int, Terminal], dict[int, Terminal]]:
    """Fold rated splitter chains into columns within the legal bank height."""
    leaves: dict[int, Terminal] = {}
    roots: dict[int, Terminal] = {}
    x = min(building.x for building in constructor.canvas.buildings) - 10
    plan = plan_proliferator_banks(inventory, height)
    directions = ((1, 0), (0, -1), (0, 1), (-1, 0))
    for group_index, supply in enumerate(inventory.supplies):
        if len(supply.coatings) == 1:
            continue
        positions = [(x + px, 14 + py) for px, py in plan.nodes[group_index]]
        nodes = [constructor.splitter(px, py, supply.item) for px, py in positions]
        # Shelf placement changes recipe order. Pair physical leaf rows with
        # physical coating rows before rating the continuation links.
        ordered_slots = sorted(
            range(len(supply.coatings)),
            key=lambda slot: (positions[min(slot // 2, len(nodes) - 1)][1], slot),
        )
        ordered_members = sorted(
            supply.coatings,
            key=lambda member: (
                constructor.canvas.buildings[inventory.coatings[member].inlet.belt].y,
                constructor.canvas.buildings[inventory.coatings[member].inlet.belt].x,
                member,
            ),
        )
        members = [0] * len(supply.coatings)
        for slot, member in zip(ordered_slots, ordered_members, strict=True):
            members[slot] = member
        remaining_rate = supply.rate
        offset = 0
        for index, node in enumerate(nodes):
            px, py = positions[index]
            incoming = (
                (-1, 0)
                if index == 0
                else (
                    (positions[index - 1][0] - px) // 10,
                    (positions[index - 1][1] - py) // 6,
                )
            )
            if index == 0:
                roots[group_index] = constructor.dock(node, incoming, feed=True)
            onward = (
                (
                    (positions[index + 1][0] - px) // 10,
                    (positions[index + 1][1] - py) // 6,
                )
                if index + 1 < len(nodes)
                else None
            )
            for direction in directions:
                if direction in (incoming, onward) or offset == len(supply.coatings):
                    continue
                coating_index = members[offset]
                leaves[coating_index] = constructor.dock(node, direction, feed=False)
                remaining_rate -= inventory.coatings[coating_index].supply_rate
                offset += 1
            if onward is not None:
                source = constructor.dock(node, onward, feed=False)
                sink = constructor.dock(nodes[index + 1], (-onward[0], -onward[1]), feed=True)
                constructor.connect(
                    source.port,
                    sink.port,
                    [(px, py, 0), (*positions[index + 1], 0)],
                    supply.item,
                    remaining_rate,
                    "local-proliferator-tree",
                )
        assert offset == len(supply.coatings) and remaining_rate == 0
    return leaves, roots


@dataclass(frozen=True, slots=True)
class BoundaryPlan:
    rows: dict[int, int]
    supply_rows: tuple[int, ...]
    width: int
    height: int


def _boundary_plan(inventory: Inventory) -> BoundaryPlan:
    roots = external_roots(inventory)
    families: dict[int, list[int]] = defaultdict(list)
    for ordinal, root in roots.items():
        families[root].append(ordinal)
    rows: dict[int, int] = {}
    y = 0
    width = _BOUNDARY_CLEARANCE
    for family in families.values():
        # A plain boundary belt needs one row. Only a real splitter tree
        # needs north/south approaches and the continuation-node pitch.
        shared = len(family) > 1
        row = y + (2 if shared else 0)
        rows.update((ordinal, row) for ordinal in family)
        y += junctions.tree_extent(len(family)) if shared else 1
        if shared:
            width = _BOUNDARY_CLEARANCE + 4
    supply_rows = tuple(range(y, y + len(inventory.supplies)))
    height = max(
        y + len(supply_rows),
        sum(demand.role == "output" for demand in inventory.demands),
    )
    return BoundaryPlan(rows, supply_rows, width, height)


def _bank_shelves(
    sizes: list[tuple[int, int]],
    height: int,
    width: int,
    inventory: Inventory,
    budget: WorkBudget,
) -> tuple[list[list[int]], int]:
    """Choose a shelf height using the complete boundary and supply envelope."""
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][0], -sizes[i][1], i))
    for i in order:
        if sizes[i][1] > height:
            raise ConstructionRefusal(f"strip {i} exceeds the legal bank height")
    boundary = _boundary_plan(inventory)
    selected: list[list[int]] = []
    selected_height = height
    best: tuple[int, int, int, int] | None = None
    for limit in range(height, max(h for _, h in sizes) - 1, -1):
        budget.check()
        banks: list[list[int]] = []
        used_heights: list[int] = []
        bank_widths: list[int] = []
        for i in order:
            bank_index = next(
                (j for j, used in enumerate(used_heights) if used + sizes[i][1] <= limit),
                len(banks),
            )
            if bank_index == len(banks):
                banks.append([])
                used_heights.append(0)
                bank_widths.append(sizes[i][0])
            banks[bank_index].append(i)
            used_heights[bank_index] += sizes[i][1]
        # Envelope estimates guide packing, not admission. Keep the previous
        # maximum-height construction if no conservative estimate fits.
        if limit == height:
            selected = banks
        supply_bounds = plan_proliferator_banks(inventory, limit).bounds
        supply_width = 0 if supply_bounds is None else max(0, 10 - supply_bounds[0])
        supply_height = 0 if supply_bounds is None else 4 + supply_bounds[3]
        # The disjoint boxes already contain every mandatory launch/landing cell.
        # Their shared boundary can supply a candidate track without an empty column.
        used_width = sum(bank_widths) + boundary.width + _BOUNDARY_CLEARANCE + supply_width
        used_height = max(max(used_heights), boundary.height, supply_height)
        score = (used_width * used_height, used_height, used_width, limit)
        if used_width <= width and used_height <= height + 12 and (best is None or score < best):
            best = score
            selected = banks
            selected_height = limit
    return selected, selected_height


def construct(
    spec: BuildSpec,
    rules: catalog.BeltAltitudeRules,
    policy: BandPolicy,
    session: RoutingRun,
    *,
    project_candidate: Callable[[Placement], Placement],
) -> Placement:
    budget = session.budget
    budget.check()
    constructor = TemplateConstructor(spec, rules, session)
    inventory = prepare_inventory(spec, rules, policy, budget)
    selected = select_topology(spec, inventory, session.order, budget)
    inventory, rates = (selected.inventory, selected.rates)
    demands = list(inventory.demands)
    for coating in inventory.coatings:
        if coating.outlet is not None and coating.consumer is not None:
            ordinal = len(demands)
            demands.append(
                TransportDemand(
                    ordinal,
                    coating.item,
                    CargoDomain.REQUIRES_SPRAY.value,
                    coating.outlet,
                    coating.consumer,
                    "local-coating",
                )
            )
            rates[ordinal] = coating.cargo_rate
    inventory = replace(inventory, demands=tuple(demands))

    def cancelled() -> bool:
        return budget.clock() >= budget.deadline

    source_families: dict[int, list[TransportDemand]] = defaultdict(list)
    sink_families: dict[int, list[TransportDemand]] = defaultdict(list)
    for demand in inventory.demands:
        if demand.source:
            source_families[demand.source.belt].append(demand)
        if demand.sink:
            sink_families[demand.sink.belt].append(demand)
    source_nodes: dict[int, list[int]] = defaultdict(list)
    source_access: dict[int, int] = {}
    source_extensions: dict[int, int] = {}
    strip_sources: dict[int, list[int]] = defaultdict(list)
    for belt, family in source_families.items():
        endpoint = family[0].source
        assert endpoint is not None
        source_access[belt] = len(strip_sources[endpoint.strip])
        # Global singleton paths choose their own exact adapter in the solver.
        # Only fixed local interfaces require the ranked ground prefix.
        extension = (
            2 * source_access[belt] if len(family) > 1 or family[0].role == "local-coating" else 0
        )
        if family[0].role == "local-coating":
            extension += max(0, inventory.modules[endpoint.strip].width - endpoint.x)
        source_extensions[belt] = extension
        strip_sources[endpoint.strip].append(belt)
        if len(family) > 1:
            source_nodes[endpoint.strip].append(belt)
    sink_nodes: dict[int, list[int]] = defaultdict(list)
    sink_access: dict[int, int] = {}
    strip_sinks: dict[int, list[int]] = defaultdict(list)
    for belt, family in sink_families.items():
        endpoint = family[0].sink
        assert endpoint is not None
        # Coating transfers approach along distinct consumer rows from the east.
        # They need no global inlet/collector rank on the module's west edge.
        sink_access[belt] = (
            0
            if family[0].role == "local-coating"
            else sum(
                sink_families[previous][0].role != "local-coating"
                for previous in strip_sinks[endpoint.strip]
            )
        )
        strip_sinks[endpoint.strip].append(belt)
        if len(family) > 1:
            sink_nodes[endpoint.strip].append(belt)
    source_rows = _tree_rows(inventory, source_families, strip_sources, source_nodes, 1, budget)
    sink_rows = _tree_rows(inventory, sink_families, strip_sinks, sink_nodes, -1, budget)
    sizes: list[tuple[int, int]] = []
    west_edges: list[int] = []
    for i, module in enumerate(inventory.modules):
        height = module.height
        for belt in source_nodes[i]:
            height = max(
                height, source_rows[belt] + junctions.tree_extent(len(source_families[belt])) - 2
            )
        for belt in sink_nodes[i]:
            height = max(
                height, sink_rows[belt] + junctions.tree_extent(len(sink_families[belt])) - 2
            )
        # Pack the complete fixed access envelope, not just strip/coater bodies.
        # Ranked approaches must not meet a neighboring bank's launch risers.
        west, east = 0, module.width
        for belt in strip_sources[i]:
            endpoint = source_families[belt][0].source
            assert endpoint is not None
            reach = max(
                source_extensions[belt] + 2,
                6 if len(source_families[belt]) > 1 else 0,
            )
            east = max(east, endpoint.x + reach + 1)
        for belt in strip_sinks[i]:
            endpoint = sink_families[belt][0].sink
            assert endpoint is not None
            reach = max(
                (
                    2 * (sink_access[belt] + 1)
                    if len(sink_families[belt]) > 1
                    or sink_families[belt][0].role == "local-coating"
                    else 2
                ),
                6 if len(sink_families[belt]) > 1 else 0,
            )
            west = min(west, endpoint.x - reach)
        west_edges.append(west)
        # Every tree's actual side seat includes its complete directed access
        # envelope; no full-width apron is needed below an independently seated tree.
        sizes.append((east - west, height))
    band_height, band_width = max(
        (height, width)
        for height, width in BAND_DIMENSIONS
        if policy.explicit_segments is None or width == policy.explicit_segments * 5
    )
    banks, bank_height = _bank_shelves(sizes, band_height - 12, band_width, inventory, budget)
    origins: dict[int, tuple[int, int]] = {}
    bank_edges: list[tuple[int, int]] = []
    x = 10
    for bank in banks:
        width = max(sizes[i][0] for i in bank)
        bank_edges.append((x, x + width))
        y = 10
        for i in bank:
            origins[i] = (x - west_edges[i], y)
            y += sizes[i][1]
        x += width
    x_tracks = tuple(
        ((left[1] + right[0]) // 2 for left, right in zip(bank_edges, bank_edges[1:], strict=False))
    )
    y_tracks = tuple(
        sorted(
            {
                (origins[left][1] + inventory.modules[left].height + origins[right][1]) // 2
                for bank in banks
                for left, right in zip(bank, bank[1:], strict=False)
            }
        )
    )
    constructor.set_tracks(x_tracks, y_tracks)
    middle_x = bank_edges[0][1]
    physical: dict[int, rd._Port] = {}
    prepared = rd._prepare_transport_inventory(
        spec,
        list(inventory.strips),
        rd._Pack(
            {
                index: (
                    origins[index][0] + module.origin[0],
                    origins[index][1] + module.origin[1],
                )
                for index, module in enumerate(inventory.modules)
            },
            x,
            bank_height,
            "transport-replay",
        ),
        belt_rules=rules,
        cancelled=cancelled,
        coater_node_sites={
            (coating.inlet.strip, coating.item): (
                origins[coating.inlet.strip][0] + coating.inlet.x,
                origins[coating.inlet.strip][1] + coating.inlet.y,
            )
            for coating in inventory.coatings
            if coating.outlet is not None
        },
    )
    constructor.canvas = prepared.canvas
    # Coater admission shares the canvas's finite projection capacity. Establish
    # this compiler's complete bank/boundary envelope before that stage; its
    # machine-only fallback otherwise excludes not-yet-emitted fixed accesses.
    supply_bounds = plan_proliferator_banks(inventory, bank_height).bounds
    planned_left = bank_edges[0][0]
    if supply_bounds is not None:
        planned_left += supply_bounds[0] - 10
    boundary = _boundary_plan(inventory)
    boundary_height = max(
        10 + bank_height,
        10 + boundary.height,
        14 + supply_bounds[3] if supply_bounds is not None else 10,
    )
    constructor.canvas.limit = (
        planned_left - 12 - 8,
        2,
        bank_edges[-1][1] + 16,
        boundary_height + 8,
    )
    coaters = (
        rd._place_coaters(
            constructor.canvas,
            spec,
            list(inventory.strips),
            prepared.strip_in_ports,
            constructor.belt_id,
            constructor.belt_model,
            policy=policy,
            cancelled=cancelled,
        )
        if inventory.coatings
        else []
    )
    endpoints = {
        endpoint
        for demand in inventory.demands
        for endpoint in (demand.source, demand.sink)
        if endpoint is not None
    }
    endpoints.update(
        endpoint
        for coating in inventory.coatings
        for endpoint in (coating.inlet, coating.outlet, coating.consumer)
        if endpoint is not None
    )
    for endpoint in endpoints:
        building = constructor.canvas.buildings[endpoint.belt]
        ox, oy = origins[endpoint.strip]
        assert (building.x, building.y, int(building.z)) == (
            ox + endpoint.x,
            oy + endpoint.y,
            endpoint.z,
        )
        physical[endpoint.belt] = rd._Port(endpoint.belt, building.x, building.y, z=int(building.z))
    sources: dict[int, Terminal] = {}
    sinks: dict[int, Terminal] = {}
    for belt, family in source_families.items():
        port = physical[belt]
        if len(family) == 1:
            if distance := source_extensions[belt]:
                terminal = constructor.belt((port.x + distance, port.y, port.z), family[0].item)
                constructor.connect(
                    port,
                    terminal,
                    [(port.x, port.y, port.z), (terminal.x, terminal.y, terminal.z)],
                    family[0].item,
                    rates[family[0].ordinal],
                    "local-source-access",
                )
                port = terminal
            sources[family[0].ordinal] = Terminal(port, (1, 0))
            continue
        endpoint = family[0].source
        assert endpoint is not None
        ox, oy = origins[endpoint.strip]
        node = constructor.splitter(port.x + 4, oy + source_rows[belt], family[0].item)
        inlet = constructor.dock(node, (-1, 0), feed=True)
        constructor.flight(
            Terminal(port, (1, 0)),
            inlet,
            family[0].item,
            sum((rates[d.ordinal] for d in family), Fraction()),
            1 + source_access[belt],
            port.x + 2 + 2 * source_access[belt],
            "local-source",
        )
        leaves = junctions.terminals(
            constructor, node, [rates[d.ordinal] for d in family], feed=False
        )
        sources.update(((d.ordinal, leaf) for d, leaf in zip(family, leaves, strict=True)))
    sinks = _sink_terminals(
        constructor, sink_families, physical, rates, origins, sink_access, sink_rows
    )
    supply_sources, supply_roots = _proliferator_terminals(constructor, inventory, bank_height)
    flight_index = 0
    output_index = 0
    external_x = min(int(b.x) for b in constructor.canvas.buildings) - boundary.width
    right_edge = max(p.x for p in physical.values()) + 6
    right_edge = (
        max(
            max(int(building.x) for building in constructor.canvas.buildings),
            max(
                (
                    point[0]
                    for flight in constructor.pending
                    if flight.role in ("local-source", "local-sink")
                    for point in flight.points(flight.exclusive_level)
                ),
                default=right_edge,
            ),
        )
        + _BOUNDARY_CLEARANCE
    )
    shared_external: dict[int, list[TransportDemand]] = {}
    for item, _, members in inventory.shared_groups:
        family = [
            d
            for d in inventory.demands
            if d.source is None
            and d.item == item
            and (d.sink is not None)
            and (d.sink.belt in members)
        ]
        for demand in family:
            shared_external[demand.ordinal] = family
    coating_level = max(
        (
            flight.exclusive_level + 1
            for flight in constructor.pending
            if flight.role in ("local-source", "local-sink")
        ),
        default=3,
    )
    coating_level = max(3, coating_level)
    if inventory.coatings and coating_level >= constructor.canvas.levels:
        raise ConstructionRefusal("coating transfers exceed the legal module altitude")
    for demand in inventory.demands:
        if cancelled():
            raise rd._PreparationDeadline
        if demand.role == "output":
            port = sources[demand.ordinal].port
            target = constructor.belt((right_edge, 10 + output_index, 0), demand.item)
            output_index += 1
            constructor.flight(
                sources[demand.ordinal],
                Terminal(target, (-1, 0)),
                demand.item,
                rates[demand.ordinal],
                3 + flight_index,
                (port.x + target.x) // 2,
                "output",
            )
            flight_index += 1
            continue
        source = sources.get(demand.ordinal)
        if source is None:
            root = constructor.belt(
                (external_x, 10 + boundary.rows[demand.ordinal], 0), demand.item
            )
            if demand.ordinal in shared_external:
                family = shared_external[demand.ordinal]
                total = sum((rates[d.ordinal] for d in family), Fraction())
                assert total <= spec.lane_capacity * spec.planning_stack(demand.item, external=True)
                node = constructor.splitter(root.x + 4, root.y, demand.item)
                inlet = constructor.dock(node, (-1, 0), feed=True)
                constructor.connect(
                    root,
                    inlet.port,
                    [(root.x, root.y, 0), (inlet.port.x, inlet.port.y, 0)],
                    demand.item,
                    total,
                    "shared-external-feed",
                )
                leaves = junctions.terminals(
                    constructor, node, [rates[d.ordinal] for d in family], feed=False
                )
                sources.update(((d.ordinal, leaf) for d, leaf in zip(family, leaves, strict=True)))
                source = sources[demand.ordinal]
            else:
                source = Terminal(root, (1, 0))
        if demand.role == "local-coating":
            # Leave the coater row along the ground, then cross the consumer
            # row from outside the machine's east edge. Turning west above the
            # coater inlet roofs every global approach to that inlet.
            sink = sinks[demand.ordinal]
            local = Flight(
                source,
                sink,
                demand.item,
                rates[demand.ordinal],
                coating_level,
                source.port.x + 2,
                demand.role,
            )
            constructor.connect(
                source.port,
                sink.port,
                local.points(coating_level),
                demand.item,
                rates[demand.ordinal],
                demand.role,
            )
            continue
        constructor.flight(
            source,
            sinks[demand.ordinal],
            demand.item,
            rates[demand.ordinal],
            3 + flight_index,
            middle_x,
            demand.role,
        )
        flight_index += 1
    for group_index, supply_plan in enumerate(inventory.supplies):
        root = constructor.belt(
            (external_x, 10 + boundary.supply_rows[group_index], 0), supply_plan.item
        )
        if group_index in supply_roots:
            constructor.flight(
                Terminal(root, (1, 0)),
                supply_roots[group_index],
                supply_plan.item,
                supply_plan.rate,
                3 + flight_index,
                middle_x,
                "proliferator-feed",
            )
            flight_index += 1
        else:
            supply_sources[supply_plan.coatings[0]] = Terminal(root, (1, 0))
    for coating_index, coating in enumerate(inventory.coatings):
        coating_inlet = prepared.strip_in_ports[coating.inlet.strip][coating.item]
        coater = next(coater for coater in coaters if coater.host_belt in coating_inlet.tiles)
        approach = constructor.canvas.buildings[coater.approach_belt]
        supply = constructor.canvas.buildings[coater.supply_belt]
        terminal = rd._Port(coater.approach_belt, approach.x, approach.y, z=int(approach.z))
        constructor.flight(
            supply_sources[coating_index],
            Terminal(terminal, (supply.x - coater.host_x, supply.y - coater.host_y)),
            coating.proliferator,
            coating.supply_rate,
            3 + flight_index,
            middle_x,
            "proliferator",
        )
        flight_index += 1
    constructor.finish()
    x0, y0, x1, y1 = rd._core_bounds(constructor.canvas)
    rx0, ry0, rx1, ry1 = rd._power_reservation(constructor.canvas.power_building)
    # A dense bank may fill its occupied envelope completely. Standing ground
    # is not power demand: allow one real tower-clearance footprint outside
    # the routed core, without adding an apron to any module or emitted area.
    constructor.canvas.limit = (
        x0 - (rx1 - rx0),
        y0 - (ry1 - ry0),
        x1 + (rx1 - rx0),
        y1 + (ry1 - ry0),
    )
    demand_box = (
        10,
        10,
        right_edge,
        max((oy + inventory.modules[i].height for i, (_, oy) in origins.items())),
    )
    projected: Placement | None = None

    def complete_plan_failure(
        towers: tuple[PlacedBuilding, ...],
    ) -> finalize.ProjectionFailure | None:
        nonlocal projected
        budget.check()
        candidate = Placement(
            buildings=assign_sorter_slots((*constructor.canvas.buildings, *towers))
        )
        try:
            projected = project_candidate(candidate)
        except finalize.ProjectionRefusal as exc:
            return exc.failures[0]
        return None

    try:
        sites = rd._power_plan(
            constructor.canvas,
            demand_box,
            policy=policy,
            cancelled=cancelled,
            complete_plan_failure=complete_plan_failure,
        )
        constructor.canvas.keep_out.clear()
        rd._place_power(constructor.canvas, sites)
    except rd._Unpowerable as exc:
        if exc.failures:
            raise finalize.ProjectionRefusal(exc.failures) from exc
        raise ConstructionRefusal(str(exc)) from exc
    if projected is None:
        projected = project_candidate(
            Placement(buildings=assign_sorter_slots(constructor.canvas.buildings))
        )
    budget.check()
    return projected
