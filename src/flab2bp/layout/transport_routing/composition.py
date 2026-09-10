"""Construct complete physical transport from exact strip obligations."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout import freeform
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.band_policy import BAND_DIMENSIONS, BandPolicy
from flab2bp.layout.base import Placement
from flab2bp.layout.slots import assign_sorter_slots
from flab2bp.spec import BuildSpec

from . import junctions
from .allocation import select_topology
from .construction import ConstructionRefusal, Constructor, Terminal
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


def _bank_shelves(sizes: list[tuple[int, int]], height: int) -> list[list[int]]:
    banks: list[list[int]] = []
    used_heights: list[int] = []
    for i in sorted(range(len(sizes)), key=lambda i: (-sizes[i][0], -sizes[i][1], i)):
        if sizes[i][1] > height:
            raise ConstructionRefusal(f"strip {i} exceeds the legal bank height")
        bank_index = next(
            (j for j, used in enumerate(used_heights) if used + sizes[i][1] <= height), len(banks)
        )
        if bank_index == len(banks):
            banks.append([])
            used_heights.append(0)
        banks[bank_index].append(i)
        used_heights[bank_index] += sizes[i][1]
    return banks


def construct(
    spec: BuildSpec, rules: catalog.BeltAltitudeRules, policy: BandPolicy, session: RoutingRun
) -> Placement:
    budget = session.budget
    budget.check()
    constructor = TemplateConstructor(spec, rules, session)
    inventory = prepare_inventory(spec, rules, policy, budget)
    selected = select_topology(spec, inventory, session.order, budget)
    inventory, rates = (selected.inventory, selected.rates)

    def cancelled() -> bool:
        return budget.clock() >= budget.deadline

    source_families: dict[int, list[TransportDemand]] = defaultdict(list)
    sink_families: dict[int, list[TransportDemand]] = defaultdict(list)
    for demand in inventory.demands:
        if demand.source:
            source_families[demand.source.belt].append(demand)
        if demand.sink:
            sink_families[demand.sink.belt].append(demand)
    adapted = rd._adapt(spec)
    source_nodes: dict[int, list[int]] = defaultdict(list)
    source_access: dict[int, int] = {}
    strip_sources: dict[int, list[int]] = defaultdict(list)
    for belt, family in source_families.items():
        endpoint = family[0].source
        assert endpoint is not None
        source_access[belt] = len(strip_sources[endpoint.strip])
        strip_sources[endpoint.strip].append(belt)
        if len(family) > 1:
            source = family[0].source
            assert source is not None
            source_nodes[source.strip].append(belt)
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
    for i, strip in enumerate(inventory.strips):
        access = sum(junctions.tree_extent(len(source_families[belt])) for belt in source_nodes[i])
        access = max(
            access, sum(junctions.tree_extent(len(sink_families[belt])) for belt in sink_nodes[i])
        )
        width, height = freeform._box(strip)
        sizes.append((width + 8, height + 6 + access))
    bank_height = (
        max(
            (
                height
                for height, width in BAND_DIMENSIONS
                if policy.explicit_segments is None or width == policy.explicit_segments * 5
            )
        )
        - 12
    )
    banks = _bank_shelves(sizes, bank_height)
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
    for index, strip in enumerate(inventory.strips):
        group = adapted[strip.group_key]
        ox, oy = origins[index]
        ins, outs, _, fixed = rd._emit_strip(
            constructor.canvas,
            strip,
            ox + inventory.modules[index].origin[0],
            oy + inventory.modules[index].origin[1],
            constructor.belt_id,
            constructor.belt_model,
            {item: rate * group.count for item, rate in group.outputs.items()},
            group.inputs,
            group.outputs,
            owner_strip=index,
        )
        if fixed:
            raise ConstructionRefusal("fixed piler transition is outside this interface witness")
        physical.update({p.belt: p for p in (*ins.values(), *outs.values())})
    for demand in inventory.demands:
        for endpoint in (demand.source, demand.sink):
            if endpoint is not None:
                port = physical[endpoint.belt]
                ox, oy = origins[endpoint.strip]
                assert (port.x, port.y, port.z) == (ox + endpoint.x, oy + endpoint.y, endpoint.z)
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
