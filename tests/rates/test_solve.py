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


# --- exactness regression --------------------------------------------------


#: Exact machine requirements for the example chain, derived by hand from the
#: recipe graph alone.  Deliberately taken from the *unproliferated* solve: it
#: has no mode choice, so unlike the Mk.III numbers it cannot shift when the
#: area objective or the footprint table changes.
EXACT_MACHINES = {
    "super-magnetic-ring": Fraction(3),
    "electromagnetic-turbine": Fraction(4),
    "electric-motor": Fraction(8),
    "gear": Fraction(4),
    "magnetic-coil": Fraction(4),
    "iron-ingot": Fraction(12),
    "copper-ingot": Fraction(4),
    "magnet": Fraction(33, 2),
    "energetic-graphite": Fraction(2),
}


def test_machine_counts_are_exact_not_snapped_floats(
    data: Dataset, plain: RateSolution
) -> None:
    """Guards a bug that ``isinstance(x, Fraction)`` cannot see.

    The solver works in floats.  An earlier derivation took its craft rates
    directly, snapped them to rationals with ``limit_denominator``, and used
    those -- which yielded ``999/1000`` machines of copper-ingot where the
    answer is exactly ``1``, and ``16397/22400`` of gear.  Those are genuine
    ``Fraction`` objects that pass every type assertion while being quietly
    wrong, and being wrong *upward* they occasionally push a count past an
    integer and buy a whole extra machine.

    The fix was to take only *structure* from the solver -- which columns run
    and their integer machine counts -- and re-derive every magnitude by exact
    demand propagation from the objective.

    Verified to discriminate: injecting a relative error of 1e-4 into the
    derived rates, which is merely SCIP's own default MIP gap and so entirely
    representative of what a solver returns, fails this test.
    """
    assert {g.recipe_id: g.exact_machines for g in plain.groups} == EXACT_MACHINES
    # Snapping a perturbed float lands on a large denominator; propagating
    # demand exactly through this chain cannot produce one bigger than 2.
    assert max(g.exact_machines.denominator for g in plain.groups) <= 2


def test_proliferated_rates_have_small_denominators(data: Dataset) -> None:
    """The same guard where mode choice makes the exact values move.

    The Mk.III mix depends on the area objective, so the individual values are
    not pinned here -- but exact demand propagation still cannot manufacture a
    large denominator, whereas a snapped float reliably does.
    """
    result = solve(data, parse_url(EXAMPLE_URL), tier=ProliferatorTier.MK3)
    assert result.groups
    assert max(g.exact_machines.denominator for g in result.groups) <= 1000


def test_derivation_ignores_solver_float_noise(data: Dataset) -> None:
    """The derivation must depend on the solver's structure, never its floats.

    Perturbing the reported machine counts by float noise -- the kind a solver
    genuinely returns, ``3.9999999997`` for 4 -- must not move the derived rates
    at all.  A derivation that reads magnitudes out of the solver fails this;
    one that reads only ``round(n)`` and propagates demand exactly cannot.
    """
    from flab2bp.rates.solve import _columns, _exact_rates, _resolve_chain

    request = parse_url(EXAMPLE_URL)
    targets = target_rates(data, request)
    excluded = frozenset(request.excluded_recipe_ids or ()) | data.default_recipe_excluded
    producers, _external = _resolve_chain(data, targets, excluded)
    internal = sorted(producers)
    columns = _columns(data, producers, request, ProliferatorTier.NONE, None, None)

    counts = {g.recipe_id: g.machines for g in solve(data, request).groups}
    clean = [float(counts.get(column.recipe_id, 0)) for column in columns]
    # Perturb well beyond float noise but strictly inside the rounding
    # interval, so `round(n)` is unmoved while every *magnitude* shifts.  A
    # derivation reading magnitudes out of the solver changes its answer here;
    # one reading only the rounded count cannot.
    noisy = [n - 0.3 if n else 0.0 for n in clean]
    fuzzed = [n + 0.4 if n else 0.0 for n in clean]

    from_clean = _exact_rates(columns, clean, internal, targets)
    assert _exact_rates(columns, noisy, internal, targets) == from_clean
    assert _exact_rates(columns, fuzzed, internal, targets) == from_clean

    # And the derived rates are exact, not merely equal to each other.
    by_recipe = {
        column.recipe_id: rate / column.crafts_per_second
        for column, rate in zip(columns, from_clean, strict=True)
        if rate
    }
    assert by_recipe["iron-ingot"] == Fraction(12)
    assert by_recipe["copper-ingot"] == Fraction(4)
    assert by_recipe["magnet"] == Fraction(33, 2)
