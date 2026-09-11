"""Physical spray-node routing and raw-domain boundaries in native transport."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.dsp import catalog, codec
from flab2bp.layout import freeform, validate
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.strip_variants import CargoDomain
from flab2bp.layout.transport_routing.runtime import TransportRoutingKernel
from flab2bp.spec import BuildSpec, MachineGroup, ProliferatorMode

_RULES = catalog.BeltAltitudeRules(
    max_z=catalog.belt_max_z(catalog.DEFAULT_LAB_LEVEL),
    vertical_construction=True,
    storage_level=catalog.DEFAULT_STORAGE_LEVEL,
    lab_level=catalog.DEFAULT_LAB_LEVEL,
    from_url=False,
)
_POLICY = BandPolicy("portable")


def _mixed_motor() -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=2,
                inputs_per_machine={"iron-ore": Fraction(1)},
                outputs_per_machine={"iron-ingot": Fraction(1)},
            ),
            MachineGroup(
                recipe_id="electric-motor",
                machine_item_id="assembling-machine-2",
                count=1,
                proliferator_mode=ProliferatorMode.PRODUCTS,
                inputs_per_machine={
                    "iron-ingot": Fraction(1),
                    "gear": Fraction(1, 2),
                    "magnetic-coil": Fraction(1, 2),
                },
                outputs_per_machine={"electric-motor": Fraction(5, 8)},
            ),
            MachineGroup(
                recipe_id="steel",
                machine_item_id="arc-smelter",
                count=1,
                inputs_per_machine={"iron-ingot": Fraction(1)},
                outputs_per_machine={"steel": Fraction(1, 3)},
            ),
        ),
        external_inputs={
            "iron-ore": Fraction(2),
            "gear": Fraction(1, 2),
            "magnetic-coil": Fraction(1, 2),
            "proliferator-3": Fraction(1, 30),
        },
        outputs={"electric-motor": Fraction(5, 8), "steel": Fraction(1, 3)},
        spray_lanes={"iron-ingot": False, "gear": True, "magnetic-coil": True},
        lanes_requiring_split=frozenset({"iron-ingot"}),
    )


def test_adjacent_coaters_are_supplied_without_coating_the_raw_branch() -> None:
    # Three neighboring input lanes cannot share the same short coating-link
    # column. Their distinct node links and the shared proliferator feed must
    # all reach the right machines without spraying the steel branch.
    spec = _mixed_motor()
    placement = TransportRoutingKernel(belt_rules=_RULES, band_policy=_POLICY).lay_out(
        spec, time_budget_s=15
    )
    report = validate.certify(placement, spec, belt_rules=_RULES, expect_power=True)
    assert report.ok, report.errors
    assert not report.skipped
    assert not report.by_check("prolif.sprayed_cargo_reaches_machines")
    encoded = codec.decode(codec.encode(placement))
    decoded = codec.decode(codec.encode_blueprint(encoded))
    assert encoded.hash_valid and decoded.hash_valid
    assert decoded.buildings == encoded.buildings


def test_explicit_coater_sites_cannot_overlap_another_node() -> None:
    spec = _mixed_motor()
    strips = freeform.plan_strips(spec, strip_len=48, band_policy=_POLICY)
    at = {index: (100 * index + strip.west_channel, 2) for index, strip in enumerate(strips)}
    sites = {
        (index, item): (0, -6)
        for index, strip in enumerate(strips)
        if strip.cargo_domain is CargoDomain.REQUIRES_SPRAY
        for item in strip.in_lanes
    }
    with pytest.raises(rd._Unseatable):
        rd._prepare_transport_inventory(
            spec,
            strips,
            rd._Pack(at, 100 * len(strips), 50, "overlapping-coaters"),
            belt_rules=_RULES,
            coater_node_sites=sites,
        )
