"""Physical strip obligations from the shared, pre-admission routing stage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout import freeform
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.strip_variants import CargoDomain
from flab2bp.spec import BuildSpec

from .budget import TransportRefusal, WorkBudget


@dataclass(frozen=True, slots=True)
class Endpoint:
    strip: int
    belt: int
    x: int
    y: int
    z: int


@dataclass(frozen=True, slots=True)
class TransportDemand:
    ordinal: int
    item: str
    domain: str
    source: Endpoint | None
    sink: Endpoint | None
    role: str


@dataclass(frozen=True, slots=True)
class ModulePlan:
    origin: tuple[int, int]
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class CoatingPlan:
    item: str
    inlet: Endpoint
    outlet: Endpoint | None
    consumer: Endpoint | None
    cargo_rate: Fraction
    proliferator: str
    supply_rate: Fraction


@dataclass(frozen=True, slots=True)
class ProliferatorSupply:
    item: str
    coatings: tuple[int, ...]
    rate: Fraction


@dataclass(frozen=True, slots=True)
class Inventory:
    strips: tuple[rd.Strip, ...]
    modules: tuple[ModulePlan, ...]
    demands: tuple[TransportDemand, ...]
    shared_roots: int
    prelinked: int
    shared_groups: tuple[tuple[str, str, tuple[int, ...]], ...]
    coatings: tuple[CoatingPlan, ...] = ()
    supplies: tuple[ProliferatorSupply, ...] = ()


def prepare_inventory(
    spec: BuildSpec,
    rules: catalog.BeltAltitudeRules,
    policy: BandPolicy,
    budget: WorkBudget,
) -> Inventory:
    """Reuse physical emission and allocation, without reserving router access."""
    budget.check()
    strips = freeform.plan_strips(
        spec,
        strip_len=48,
        band_policy=policy,
        cancelled=lambda: budget.clock() >= budget.deadline,
    )
    if not strips:
        raise TransportRefusal("UNSUPPORTED_INTERFACE", "no physical machine strips to connect")
    modules = tuple(ModulePlan((strip.west_channel, 0), *freeform._box(strip)) for strip in strips)
    # This disjoint capture canvas is discarded. Endpoint coordinates below are
    # module-local; the constructor selects the final, band-constrained banks.
    bases = {index: 1000 * index for index in range(len(strips))}
    at = {
        index: (bases[index] + module.origin[0], module.origin[1])
        for index, module in enumerate(modules)
    }
    prepared = rd._prepare_transport_inventory(
        spec,
        strips,
        rd._Pack(at, 1000 * len(strips), 50, "transport-inventory"),
        belt_rules=rules,
        cancelled=lambda: budget.clock() >= budget.deadline,
        coater_node_sites={
            (index, item): (bases[index], -6 * (lane + 1))
            for index, strip in enumerate(strips)
            if strip.cargo_domain is CargoDomain.REQUIRES_SPRAY
            for lane, item in enumerate(dict.fromkeys(strip.in_lanes))
        },
    )
    if prepared.piler_nets:
        raise TransportRefusal(
            "UNSUPPORTED_INTERFACE", "transport-routing does not construct fixed piler transitions"
        )

    # Include the canonical node's real footprint, not only its consumer strip.
    # Normalize each module independently so replay can translate every endpoint.
    bounds = [
        [bases[i], 0, bases[i] + module.width, module.height] for i, module in enumerate(modules)
    ]
    for building in prepared.canvas.buildings:
        if (
            building.owner_strip is None
            or strips[building.owner_strip].cargo_domain is not CargoDomain.REQUIRES_SPRAY
        ):
            continue
        box = bounds[building.owner_strip]
        box[0] = min(box[0], building.x - 1)
        box[1] = min(box[1], building.y - 2)
        box[2] = max(box[2], building.x + building.width + 1)
        box[3] = max(box[3], building.y + building.height + 1)
    modules = tuple(
        ModulePlan(
            (module.origin[0] + bases[i] - box[0], module.origin[1] - box[1]),
            box[2] - box[0],
            box[3] - box[1],
        )
        for i, (module, box) in enumerate(zip(modules, bounds, strict=True))
    )

    def endpoint(port: rd._Port | None) -> Endpoint | None:
        if port is None:
            return None
        owner = prepared.strip_of_belt[port.belt]
        return Endpoint(
            owner, port.belt, port.x - bounds[owner][0], port.y - bounds[owner][1], port.z
        )

    demands: list[TransportDemand] = []

    def add(
        item: str, domain: str, source: Endpoint | None, sink: Endpoint | None, role: str
    ) -> None:
        budget.check()
        demands.append(TransportDemand(len(demands), item, domain, source, sink, role))

    groups = rd._adapt(spec)
    coatings: list[CoatingPlan] = []
    coating_links: set[tuple[int, int]] = set()
    proliferator = rd._proliferator_item(spec)
    for index, ports in enumerate(prepared.strip_in_ports):
        group = groups[strips[index].group_key]
        for item, port in ports.items():
            if port.cargo_domain is not CargoDomain.REQUIRES_SPRAY:
                continue
            if proliferator is None:
                raise TransportRefusal("COATER_SUPPLY", "a sprayed lane has no proliferator input")
            inlet = endpoint(port)
            assert inlet is not None
            local = next(
                (
                    net
                    for net in prepared.nets
                    if net.src is not None and net.src.belt in port.tiles
                ),
                None,
            )
            if local is not None:
                coating_links.add((local.source.belt, local.dst.belt))
            coatings.append(
                CoatingPlan(
                    item,
                    inlet,
                    endpoint(local.source) if local is not None else None,
                    endpoint(local.dst) if local is not None else None,
                    group.inputs[item] * strips[index].machines,
                    proliferator,
                    Fraction(),
                )
            )
    if coatings:
        assert proliferator is not None
        # The frozen spec already contains tier/mode-adjusted spray consumption.
        # Attribute that exact boundary obligation by each lane's coated cargo.
        spray_rate = spec.external_inputs[proliferator] - sum(
            (group.inputs.get(proliferator, Fraction()) * group.count for group in groups.values()),
            Fraction(),
        )
        cargo_rate = sum((coating.cargo_rate for coating in coatings), Fraction())
        if spray_rate <= 0 or cargo_rate <= 0:
            raise TransportRefusal("COATER_SUPPLY", "sprayed lanes have no positive supply budget")
        coatings = [
            replace(coating, supply_rate=spray_rate * coating.cargo_rate / cargo_rate)
            for coating in coatings
        ]
        capacity = spec.lane_capacity * spec.planning_stack(proliferator, external=True)
        if any(coating.supply_rate > capacity for coating in coatings):
            raise TransportRefusal("COATER_SUPPLY", "a coater supply exceeds one legal input lane")
    for net in prepared.nets:
        if not net.prelinked and (net.source.belt, net.dst.belt) not in coating_links:
            source, sink = endpoint(net.src), endpoint(net.dst)
            role = (
                "local"
                if source is not None and sink is not None and source.strip == sink.strip
                else "internal"
            )
            add(net.item, net.cargo_domain.value, source, sink, role)
    for belt, (port, _) in prepared.wanted.items():
        add(prepared.carried[belt], port.cargo_domain.value, None, endpoint(port), "external")
    # Shared-input roots replace the member lanes in `wanted`. Every original
    # member remains an obligation, while allocation spends their one root cap.
    roots = set(prepared.wanted)
    for item, domain, shared_ports in prepared.shared_external_groups:
        for port in shared_ports:
            if port.belt not in roots:
                add(item, domain.value, None, endpoint(port), "external")
    for item, port in prepared.wanted_outputs.values():
        add(item, port.cargo_domain.value, endpoint(port), None, "output")
    supply_members: list[list[int]] = []
    supply_rates: list[Fraction] = []
    for index, coating in enumerate(coatings):
        capacity = spec.lane_capacity * spec.planning_stack(coating.proliferator, external=True)
        group_index = next(
            (
                i
                for i, members in enumerate(supply_members)
                if coatings[members[0]].proliferator == coating.proliferator
                and supply_rates[i] + coating.supply_rate <= capacity
            ),
            len(supply_members),
        )
        if group_index == len(supply_members):
            supply_members.append([])
            supply_rates.append(Fraction())
        supply_members[group_index].append(index)
        supply_rates[group_index] += coating.supply_rate
    return Inventory(
        tuple(strips),
        modules,
        tuple(demands),
        len(prepared.shared_external_groups),
        sum(net.prelinked for net in prepared.nets),
        tuple(
            (item, domain.value, tuple(port.belt for port in ports))
            for item, domain, ports in prepared.shared_external_groups
        ),
        tuple(coatings),
        tuple(
            ProliferatorSupply(coatings[members[0]].proliferator, tuple(members), rate)
            for members, rate in zip(supply_members, supply_rates, strict=True)
        ),
    )
