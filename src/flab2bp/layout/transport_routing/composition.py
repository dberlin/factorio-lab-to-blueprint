"""Construct complete physical transport from exact strip obligations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.band_policy import BAND_DIMENSIONS, BandPolicy
from flab2bp.layout.base import Placement
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


def _sink_terminals(
    constructor: Constructor,
    inventory: Inventory,
    sink_families: dict[int, list[TransportDemand]],
    physical: dict[int, rd._Port],
    rates: dict[int, Fraction],
    origins: dict[int, tuple[int, int]],
    sink_access: dict[int, int],
    sink_nodes: dict[int, list[int]],
) -> dict[int, Terminal]:
    sinks: dict[int, Terminal] = {}
    for belt, family in sink_families.items():
        port = physical[belt]
        if len(family) == 1:
            if distance := (2 * sink_access[belt]):
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
        rank = sink_nodes[endpoint.strip].index(belt)
        offset = sum(
            junctions.tree_extent(len(sink_families[previous]))
            for previous in sink_nodes[endpoint.strip][:rank]
        )
        node = constructor.splitter(
            port.x - 4,
            origins[endpoint.strip][1] + inventory.modules[endpoint.strip].height + 2 + offset,
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
    boundary_height = max(
        6 * (len(set(external_roots(inventory).values())) + len(inventory.supplies)),
        3 * sum(demand.role == "output" for demand in inventory.demands),
    )
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
        used_width = sum(bank_widths) + 24 * (len(banks) - 1) + 36 + supply_width
        used_height = max(max(used_heights), boundary_height, supply_height) + 12
        score = (used_width * used_height, used_height, used_width, limit)
        if used_width <= width and used_height <= height + 12 and (best is None or score < best):
            best = score
            selected = banks
            selected_height = limit
    return selected, selected_height


def construct(
    spec: BuildSpec, rules: catalog.BeltAltitudeRules, policy: BandPolicy, session: RoutingRun
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
    strip_sources: dict[int, list[int]] = defaultdict(list)
    for belt, family in source_families.items():
        endpoint = family[0].source
        assert endpoint is not None
        source_access[belt] = len(strip_sources[endpoint.strip])
        strip_sources[endpoint.strip].append(belt)
        if len(family) > 1:
            source_nodes[endpoint.strip].append(belt)
    sink_nodes: dict[int, list[int]] = defaultdict(list)
    sink_access: dict[int, int] = {}
    strip_sinks: dict[int, list[int]] = defaultdict(list)
    for belt, family in sink_families.items():
        endpoint = family[0].sink
        assert endpoint is not None
        sink_access[belt] = len(strip_sinks[endpoint.strip])
        strip_sinks[endpoint.strip].append(belt)
        if len(family) > 1:
            sink_nodes[endpoint.strip].append(belt)
    sizes: list[tuple[int, int]] = []
    for i, module in enumerate(inventory.modules):
        access = sum(junctions.tree_extent(len(source_families[belt])) for belt in source_nodes[i])
        access = max(
            access, sum(junctions.tree_extent(len(sink_families[belt])) for belt in sink_nodes[i])
        )
        sizes.append((module.width + 8, module.height + 4 + access))
    band_height, band_width = max(
        (height, width)
        for height, width in BAND_DIMENSIONS
        if policy.explicit_segments is None or width == policy.explicit_segments * 5
    )
    banks, bank_height = _bank_shelves(sizes, band_height - 12, band_width, inventory, budget)
    origins: dict[int, tuple[int, int]] = {}
    bank_widths: list[int] = []
    x = 10
    for bank in banks:
        width = max(sizes[i][0] for i in bank)
        bank_widths.append(width)
        y = 10
        for i in bank:
            origins[i] = (x, y)
            y += sizes[i][1]
        x += width + 24
    bank_edges = [
        (origins[bank[0]][0], origins[bank[0]][0] + width)
        for bank, width in zip(banks, bank_widths, strict=True)
    ]
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
    middle_x = 10 + bank_widths[0] + 12
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
            if distance := (2 * source_access[belt]):
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
        rank = source_nodes[endpoint.strip].index(belt)
        ox, oy = origins[endpoint.strip]
        offset = sum(
            junctions.tree_extent(len(source_families[previous]))
            for previous in source_nodes[endpoint.strip][:rank]
        )
        node = constructor.splitter(
            port.x + 4, oy + inventory.modules[endpoint.strip].height + 2 + offset, family[0].item
        )
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
        constructor, inventory, sink_families, physical, rates, origins, sink_access, sink_nodes
    )
    supply_sources, supply_roots = _proliferator_terminals(constructor, inventory, bank_height)
    flight_index = 0
    external_index = 0
    output_index = 0
    external_x = min(int(b.x) for b in constructor.canvas.buildings) - 12
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
        + 8
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
            target = constructor.belt((right_edge, 10 + 3 * output_index, 0), demand.item)
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
            root = constructor.belt((external_x, 10 + 6 * external_index, 0), demand.item)
            external_index += 1
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
            # Node rows run away from the machine band in the same order that
            # consumer access columns run west. Their nested transfers therefore
            # share one overflight plane without crossing another coating link.
            sink = sinks[demand.ordinal]
            local = Flight(
                source,
                sink,
                demand.item,
                rates[demand.ordinal],
                coating_level,
                sink.port.x - 2,
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
        root = constructor.belt((external_x, 10 + 6 * external_index, 0), supply_plan.item)
        external_index += 1
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
    constructor.canvas.limit = rd._core_bounds(constructor.canvas)
    demand_box = (
        10,
        10,
        right_edge,
        max((oy + inventory.modules[i].height for i, (_, oy) in origins.items())),
    )
    sites = rd._power_plan(constructor.canvas, demand_box, policy=policy, cancelled=cancelled)
    constructor.canvas.keep_out.clear()
    rd._place_power(constructor.canvas, sites)
    placement = Placement(buildings=assign_sorter_slots(constructor.canvas.buildings))
    budget.check()
    return placement
