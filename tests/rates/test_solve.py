"""The production solve: objectives in, exact machine counts out."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.lab.data import load_dataset
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.adjust import ProliferatorTier
from flab2bp.rates.solve import RateSolution, solve, target_rates
from flab2bp.spec import ProliferatorMode

EXAMPLE_URL = (
    "https://factoriolab.github.io/dsp/flow"
    "?o=super-magnetic-ring*60"
    "&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
    "&mps=proliferator-2-products"
    "&v=11"
)

#: From the design spec's golden table, hand-verified against the recipe graph.
GOLDEN_COUNTS = {
    "super-magnetic-ring": 3,
    "electromagnetic-turbine": 4,
    "electric-motor": 8,
    "gear": 4,
    "magnetic-coil": 4,
    "iron-ingot": 12,
    "copper-ingot": 4,
    "magnet": 17,  # 33/2 exact, rounded up
    "energetic-graphite": 2,
}

GOLDEN_MACHINES = {
    "super-magnetic-ring": "assembling-machine-2",
    "electromagnetic-turbine": "assembling-machine-2",
    "electric-motor": "assembling-machine-2",
    "gear": "assembling-machine-2",
    "magnetic-coil": "assembling-machine-2",
    "iron-ingot": "arc-smelter",
    "copper-ingot": "arc-smelter",
    "magnet": "arc-smelter",
    "energetic-graphite": "arc-smelter",
}


@pytest.fixture(scope="module")
def data() -> Dataset:
    return load_dataset()


@pytest.fixture(scope="module")
def plain(data: Dataset) -> RateSolution:
    return solve(data, parse_url(EXAMPLE_URL))


# --- objective normalisation ----------------------------------------------


def test_per_minute_objective_becomes_items_per_second(data: Dataset) -> None:
    """No ``odr`` means per-minute, so 60/min is exactly 1/s."""
    rates = target_rates(data, parse_url(EXAMPLE_URL))
    assert rates == {"super-magnetic-ring": Fraction(1)}


# --- the golden solve ------------------------------------------------------


def test_golden_machine_counts(plain: RateSolution) -> None:
    assert {g.recipe_id: g.machines for g in plain.groups} == GOLDEN_COUNTS


def test_golden_machine_assignment(plain: RateSolution) -> None:
    assert {g.recipe_id: g.machine_item_id for g in plain.groups} == GOLDEN_MACHINES


def test_magnet_exact_count_is_a_fraction_not_a_float(plain: RateSolution) -> None:
    """The float-contamination canary.

    33/2 is the one non-integral count in the chain, so any accidental float
    round-trip shows up here and nowhere else.
    """
    magnet = next(g for g in plain.groups if g.recipe_id == "magnet")
    assert isinstance(magnet.exact_machines, Fraction)
    assert magnet.exact_machines == Fraction(33, 2)
    assert magnet.machines == 17


def test_external_inputs_are_exactly_the_raw_ores(plain: RateSolution) -> None:
    """Mining is the cut line: ore arrives belted, no miners are built."""
    assert dict(plain.external_inputs) == {
        "iron-ore": Fraction(23),
        "copper-ore": Fraction(4),
        "coal": Fraction(2),
    }


def test_no_mining_machines_are_built(plain: RateSolution, data: Dataset) -> None:
    mining = {r.id for r in data.mining_recipes()}
    assert not {g.recipe_id for g in plain.groups} & mining
    assert not any(
        g.machine_item_id in {"mining-machine", "oil-extractor", "water-pump"}
        for g in plain.groups
    )


def test_output_meets_the_objective(plain: RateSolution) -> None:
    assert plain.outputs["super-magnetic-ring"] >= Fraction(1)


def test_all_rates_are_exact_fractions(plain: RateSolution) -> None:
    values = [
        *plain.external_inputs.values(),
        *plain.outputs.values(),
        *(v for g in plain.groups for v in g.inputs.values()),
        *(v for g in plain.groups for v in g.outputs.values()),
    ]
    assert values and all(isinstance(v, Fraction) for v in values)


def test_every_internal_demand_is_satisfied(plain: RateSolution) -> None:
    """No dangling demands: everything consumed is produced or belted in."""
    produced: dict[str, Fraction] = {}
    consumed: dict[str, Fraction] = {}
    for group in plain.groups:
        for item, rate in group.outputs.items():
            produced[item] = produced.get(item, Fraction(0)) + rate
        for item, rate in group.inputs.items():
            consumed[item] = consumed.get(item, Fraction(0)) + rate
    for item, want in consumed.items():
        have = produced.get(item, Fraction(0)) + plain.external_inputs.get(item, Fraction(0))
        assert have >= want, f"{item}: have {have}, need {want}"


def test_integer_rounding_never_under_produces(plain: RateSolution) -> None:
    for group in plain.groups:
        assert group.machines >= group.exact_machines
        assert group.machines >= 1


# --- proliferator ----------------------------------------------------------


def test_speed_mode_does_not_reduce_ore_demand(data: Dataset) -> None:
    """Speed mode saves machines at its own step and compounds nowhere."""
    request = parse_url(EXAMPLE_URL)
    speed_only = solve(
        data, request, tier=ProliferatorTier.MK3, allowed_modes=(ProliferatorMode.SPEED,)
    )
    assert speed_only.external_inputs["iron-ore"] == Fraction(23)


def test_products_mode_compounds_upstream(data: Dataset) -> None:
    """Products mode reduces input demand all the way up the chain."""
    request = parse_url(EXAMPLE_URL)
    products = solve(
        data, request, tier=ProliferatorTier.MK3, allowed_modes=(ProliferatorMode.PRODUCTS,)
    )
    assert products.external_inputs["iron-ore"] < Fraction(23)


def test_proliferation_reduces_machine_count(data: Dataset, plain: RateSolution) -> None:
    request = parse_url(EXAMPLE_URL)
    proliferated = solve(data, request, tier=ProliferatorTier.MK3)
    assert proliferated.exact_machine_count < plain.exact_machine_count


def test_proliferator_is_an_external_input(data: Dataset) -> None:
    """Proliferator is belted in, never built here."""
    request = parse_url(EXAMPLE_URL)
    result = solve(data, request, tier=ProliferatorTier.MK3)
    assert result.proliferator_rate > 0
    assert result.external_inputs.get("proliferator-3") == result.proliferator_rate
    assert not any(g.recipe_id.startswith("proliferator") for g in result.groups)


def test_products_mode_never_used_for_a_speed_only_recipe(data: Dataset) -> None:
    """``conveyor-belt-2`` is outside the productivity whitelist."""
    url = "https://factoriolab.github.io/dsp/flow?o=conveyor-belt-2*60&v=11"
    result = solve(data, parse_url(url), tier=ProliferatorTier.MK3)
    belt = next(g for g in result.groups if g.recipe_id == "conveyor-belt-2")
    assert belt.mode is not ProliferatorMode.PRODUCTS


def test_proliferator_tier_is_monotone_in_area(data: Dataset) -> None:
    request = parse_url(EXAMPLE_URL)
    areas = [
        solve(data, request, tier=tier).total_area
        for tier in (ProliferatorTier.NONE, ProliferatorTier.MK1, ProliferatorTier.MK3)
    ]
    assert areas[2] <= areas[0]
    assert areas[1] <= areas[0]


# --- the multi-producer LP path -------------------------------------------


def test_multi_producer_chain_solves(data: Dataset) -> None:
    """An oil chain: ``refined-oil`` and ``hydrogen`` are joint products.

    This is the case a naive recipe-tree walk cannot handle, and the reason a
    real solver is kept rather than a DAG traversal.
    """
    url = "https://factoriolab.github.io/dsp/flow?o=graphene*60&v=11"
    result = solve(data, parse_url(url))
    assert result.groups
    assert result.outputs["graphene"] >= Fraction(1)


def test_joint_product_surplus_is_reported(data: Dataset) -> None:
    """Joint products cannot generally balance exactly; surplus is declared."""
    url = "https://factoriolab.github.io/dsp/flow?o=refined-oil*60&v=11"
    result = solve(data, parse_url(url))
    assert result.outputs["refined-oil"] >= Fraction(1)
    for rate in result.surplus.values():
        assert rate >= 0
