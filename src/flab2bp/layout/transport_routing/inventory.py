"""Physical strip obligations from the shared, pre-admission routing stage."""

from __future__ import annotations

from dataclasses import dataclass

from flab2bp.dsp import catalog
from flab2bp.layout import freeform
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.band_policy import BandPolicy
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
class Inventory:
    strips: tuple[rd.Strip, ...]
    modules: tuple[ModulePlan, ...]
    demands: tuple[TransportDemand, ...]
    shared_roots: int
    prelinked: int
    shared_groups: tuple[tuple[str, str, tuple[int, ...]], ...]


def prepare_inventory(
    spec: BuildSpec,
    rules: catalog.BeltAltitudeRules,
    policy: BandPolicy,
    budget: WorkBudget,
) -> Inventory:
    """Reuse physical emission and allocation, without reserving router access."""
    budget.check()
    if spec.spray_lanes:
        raise TransportRefusal(
            "UNSUPPORTED_INTERFACE", "transport-routing does not construct sprayed interfaces"
        )
    strips = freeform.plan_strips(
        spec,
        strip_len=48,
        band_policy=policy,
        cancelled=lambda: budget.clock() >= budget.deadline,
    )
    if not strips:
        raise TransportRefusal("UNSUPPORTED_INTERFACE", "no physical machine strips to connect")
    modules = tuple(
        ModulePlan((strip.west_channel, 2), freeform._box(strip)[0], freeform._box(strip)[1] + 2)
        for strip in strips
    )
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
    )
    if prepared.piler_nets:
        raise TransportRefusal(
            "UNSUPPORTED_INTERFACE", "transport-routing does not construct fixed piler transitions"
        )

    def endpoint(port: rd._Port | None) -> Endpoint | None:
        if port is None:
            return None
        owner = prepared.strip_of_belt[port.belt]
        return Endpoint(owner, port.belt, port.x - bases[owner], port.y, port.z)

    demands: list[TransportDemand] = []

    def add(
        item: str, domain: str, source: Endpoint | None, sink: Endpoint | None, role: str
    ) -> None:
        budget.check()
        demands.append(TransportDemand(len(demands), item, domain, source, sink, role))

    for net in prepared.nets:
        if not net.prelinked:
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
    for item, domain, ports in prepared.shared_external_groups:
        for port in ports:
            if port.belt not in roots:
                add(item, domain.value, None, endpoint(port), "external")
    for item, port in prepared.wanted_outputs.values():
        add(item, port.cargo_domain.value, endpoint(port), None, "output")
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
    )
