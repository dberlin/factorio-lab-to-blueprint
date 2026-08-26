"""The production solve: objectives in, exact machine counts out."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from fractions import Fraction

import pytest
from ortools.linear_solver import pywraplp  # type: ignore[import-untyped]

from flab2bp.lab.data import load_dataset
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.adjust import AdjustedRecipe, ProliferatorTier
from flab2bp.rates.solve import (
    InfeasibleError,
    RateSolution,
    _buildable_producers,
    _exact_continuous_rates,
    _exact_rates,
    _excluded_recipes,
    solve,
    target_rates,
)
from flab2bp.spec import ProliferatorMode

solve_module = importlib.import_module("flab2bp.rates.solve")


EXAMPLE_URL = (
    "https://factoriolab.github.io/dsp/flow"
    "?o=super-magnetic-ring*60"
    "&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
    "&mps=proliferator-2-products"
    "&v=11"
)

LOW_RATE_URL = (
    "https://factoriolab.github.io/dsp/list?o=magnetic-coil*1&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
)
CONTINUOUS_ROUTE_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxFyrEKwkAURNG.ecVUu0GxmmYWYyeJoLituojEJRBQ"
    "tHnfLqJod7jckTrbSB0xmwcgvv38e4EmfLlD8zsy4icXorVKIVhlRrDLoVA2lQc7ZJww4AatoS20h"
    "wbXFan1tELqPW2s1onZ5Uvv7c4YXwAUJfU_&v=11"
)
CONTINUOUS_ROUTE_RECIPES = frozenset(
    {
        "casimir-crystal",
        "circuit-board",
        "deuterium",
        "diamond",
        "electric-motor",
        "electromagnetic-turbine",
        "energetic-graphite",
        "gear",
        "glass",
        "graphene-advanced",
        "graviton-lens",
        "gravity-matrix",
        "magnet",
        "magnetic-coil",
        "microcrystalline-component",
        "organic-crystal",
        "particle-container",
        "plane-filter",
        "plastic",
        "processor",
        "quantum-chip",
        "space-warper-advanced",
        "strange-matter",
        "titanium-crystal",
        "titanium-glass",
    }
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
        data,
        request,
        tier=ProliferatorTier.MK3,
        mode_policy=ProliferatorMode.SPEED,
    )
    assert speed_only.external_inputs["iron-ore"] == Fraction(23)


def test_products_mode_compounds_upstream(data: Dataset) -> None:
    """Products mode reduces input demand all the way up the chain."""
    request = parse_url(EXAMPLE_URL)
    products = solve(
        data,
        request,
        tier=ProliferatorTier.MK3,
        mode_policy=ProliferatorMode.PRODUCTS,
    )
    assert products.external_inputs["iron-ore"] < Fraction(23)


def test_proliferation_reduces_machine_count(data: Dataset, plain: RateSolution) -> None:
    request = parse_url(EXAMPLE_URL)
    proliferated = solve(
        data,
        request,
        tier=ProliferatorTier.MK3,
        mode_policy=ProliferatorMode.PRODUCTS,
    )
    assert proliferated.exact_machine_count < plain.exact_machine_count


def test_proliferator_is_an_external_input(data: Dataset) -> None:
    """Proliferator is belted in, never built here."""
    request = parse_url(EXAMPLE_URL)
    result = solve(
        data,
        request,
        tier=ProliferatorTier.MK3,
        mode_policy=ProliferatorMode.PRODUCTS,
    )
    assert result.proliferator_rate > 0
    assert result.external_inputs.get("proliferator-3") == result.proliferator_rate
    assert not any(g.recipe_id.startswith("proliferator") for g in result.groups)


def test_products_mode_never_used_for_a_speed_only_recipe(data: Dataset) -> None:
    """``conveyor-belt-2`` is outside the productivity whitelist."""
    url = "https://factoriolab.github.io/dsp/flow?o=conveyor-belt-2*60&v=11"
    result = solve(
        data,
        parse_url(url),
        tier=ProliferatorTier.MK3,
        mode_policy=ProliferatorMode.PRODUCTS,
    )
    belt = next(g for g in result.groups if g.recipe_id == "conveyor-belt-2")
    assert belt.mode is not ProliferatorMode.PRODUCTS


def test_proliferator_tier_is_monotone_in_area(data: Dataset) -> None:
    request = parse_url(EXAMPLE_URL)
    areas = [
        solve(data, request, tier=tier, mode_policy=ProliferatorMode.PRODUCTS).total_area
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


def test_products_policy_rates_are_exact_balanced_and_within_capacity(
    data: Dataset,
) -> None:
    result = solve(
        data,
        parse_url(EXAMPLE_URL),
        tier=ProliferatorTier.MK3,
        mode_policy=ProliferatorMode.PRODUCTS,
    )

    assert result.groups
    assert all(isinstance(group.crafts_per_second, Fraction) for group in result.groups)
    assert all(
        group.crafts_per_second
        <= group.machines * group.adjusted.crafts_per_second
        for group in result.groups
    )
    produced: dict[str, Fraction] = {}
    consumed: dict[str, Fraction] = {}
    for group in result.groups:
        for item_id, rate in group.outputs.items():
            produced[item_id] = produced.get(item_id, Fraction()) + rate
        for item_id, rate in group.inputs.items():
            consumed[item_id] = consumed.get(item_id, Fraction()) + rate
    for item_id, rate in consumed.items():
        available = produced.get(item_id, Fraction()) + result.external_inputs.get(
            item_id, Fraction()
        )
        assert available >= rate


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


# --- recipe cycles ---------------------------------------------------------


#: The URL a user reported, kept as end-to-end cover for the rate solve.
#:
#: It USED to activate both members of DSP's only recipe cycle, and these tests
#: were named for that.  It no longer does, and the reason is worth knowing:
#: ``60d5f0f`` stopped us unioning the mod's default recipe exclusions over the
#: player's own set, which restored ``graphene-advanced``.  The chain now takes
#: fire ice to graphene and never needs the refined-oil loop, so
#: ``reforming-refine`` is absent and the total fell 49 -> 41 machines.
#:
#: **No corpus URL at any tier activates a self-consuming recipe** -- I checked
#: all twelve across Mk.I/II/III.  So the divergence guard cannot live on a real
#: URL, and it does not: it lives in the synthetic ``_exact_rates`` tests below,
#: which build self-loops directly and are the real cover for the fixed-point
#: iteration that once reported 732,268 machines.  Do not re-point these at a
#: URL and assume the cycle is covered; check that the recipe is actually used.
CYCLE_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJw1xrEKwkAQBNC.2WKqPYh208yR2IkJBLxWvULiEQgo2"
    "uy3i4Wveisde7eVuqLbOZB-..xficEaBbfGArf7pVK21TdPKLhhwRM6QjN0hpbQA3mIfEAeI0.W2sYSij5Ge"
    "zGlL0XsHqc_&v=11"
)


@pytest.fixture(scope="module")
def cycle(data: Dataset) -> RateSolution:
    return solve(data, parse_url(CYCLE_URL), tier=ProliferatorTier.MK2)


def test_a_real_url_does_not_run_away(cycle: RateSolution) -> None:
    """A continuous route remains within a physically plausible scale."""
    assert Fraction(20) <= cycle.machine_count <= Fraction(80)


def test_derived_counts_are_exact_physical_ceilings(cycle: RateSolution) -> None:
    """Every group is the exact ceiling of its continuous requirement."""
    assert cycle.groups
    for group in cycle.groups:
        exact = group.exact_machines
        ceiling = -((-exact.numerator) // exact.denominator)
        assert group.machines == ceiling, (
            f"{group.recipe_id}: {group.machines} machines against an exact "
            f"requirement of {exact}"
        )
        assert group.machines >= 1


def test_recipe_cycle_balances_exactly(cycle: RateSolution) -> None:
    """Refined oil and hydrogen close, in exact rationals, cycle and all."""
    produced: dict[str, Fraction] = {}
    consumed: dict[str, Fraction] = {}
    for group in cycle.groups:
        for item, rate in group.outputs.items():
            produced[item] = produced.get(item, Fraction(0)) + rate
        for item, rate in group.inputs.items():
            consumed[item] = consumed.get(item, Fraction(0)) + rate
    for item in ("refined-oil", "hydrogen"):
        assert isinstance(produced[item], Fraction)
        assert produced[item] >= consumed.get(item, Fraction(0)), item


def test_recipe_cycle_meets_its_objective(cycle: RateSolution) -> None:
    assert cycle.outputs["information-matrix"] >= Fraction(1)


# --- the exact rate LP, on structures built by hand ------------------------


def _column(
    recipe_id: str,
    inputs: dict[str, Fraction],
    outputs: dict[str, Fraction],
    craft_time: Fraction = Fraction(1),
) -> AdjustedRecipe:
    """A bare column, so a cycle can be posed without a URL that produces one."""
    return AdjustedRecipe(
        recipe_id=recipe_id,
        machine_item_id="chemical-plant",
        mode=ProliferatorMode.NONE,
        tier=ProliferatorTier.NONE,
        craft_time=craft_time,
        inputs_per_craft=inputs,
        outputs_per_craft=outputs,
        proliferator_per_craft=Fraction(0),
        proliferator_item_id=None,
    )


def test_self_consuming_recipe_solves_in_closed_form() -> None:
    """Two in, three out: one net per craft, so demand is the answer exactly.

    The shape of ``reforming-refine``, reduced to the one column that shows it.
    The old derivation charged the maker's own two to the requirement *and*
    netted them out of the supply, which made the balance read ``x = 1 + 2x``
    and doubled every round.  Stated once and solved, it is ``x * (3 - 2) = 1``.
    """
    loop = _column("loop", {"x": Fraction(2)}, {"x": Fraction(3)})
    assert _exact_rates([loop], [5.0], ["x"], {"x": Fraction(1)}) == [Fraction(1)]


def test_two_recipe_cycle_balances_in_every_capacity_regime() -> None:
    """DSP's actual pair, driven through the regimes the MILP can hand it.

    Which member carries the load depends on how many machines were bought, and
    the balance has to close in each case -- including the one where the cheaper
    producer is capped and the reformer has to make up the difference, which is
    exactly the configuration the reporting URL lands in.
    """
    plasma = _column(
        "plasma-refining", {"crude": Fraction(2)},
        {"refined": Fraction(2), "hydrogen": Fraction(1)},
    )
    reform = _column(
        "reforming-refine",
        {"refined": Fraction(2), "hydrogen": Fraction(1), "coal": Fraction(1)},
        {"refined": Fraction(3)},
    )
    for machines in ([2.0, 1.0], [10.0, 10.0], [1.0, 10.0]):
        rates = _exact_rates(
            [plasma, reform], machines, ["refined", "hydrogen"], {"refined": Fraction(3)}
        )
        assert all(isinstance(r, Fraction) and r >= 0 for r in rates)
        refined_made = rates[0] * 2 + rates[1] * 3
        refined_used = Fraction(3) + rates[1] * 2
        assert refined_made >= refined_used, machines
        assert rates[0] >= rates[1], machines  # hydrogen: only plasma makes it
        # And never past the machines that were bought.
        for rate, count in zip(rates, machines, strict=True):
            assert rate <= Fraction(round(count)), machines


def test_the_capped_regime_puts_the_reformer_to_work() -> None:
    """Cap the cheap producer and the cycle genuinely has to turn.

    Pinned rather than merely asserted feasible, because ``reform`` running at
    all is the case the old code could not do arithmetic on.
    """
    plasma = _column(
        "plasma-refining", {"crude": Fraction(2)},
        {"refined": Fraction(2), "hydrogen": Fraction(1)},
    )
    reform = _column(
        "reforming-refine",
        {"refined": Fraction(2), "hydrogen": Fraction(1), "coal": Fraction(1)},
        {"refined": Fraction(3)},
    )
    rates = _exact_rates(
        [plasma, reform], [1.0, 10.0], ["refined", "hydrogen"], {"refined": Fraction(3)}
    )
    # Plasma is capped at one craft/s and yields two refined; the reformer turns
    # its one hydrogen and two of that oil into three, netting the last one.
    assert rates == [Fraction(1), Fraction(1)]


def test_a_structure_that_cannot_balance_refuses() -> None:
    """A demand no number of the bought machines can reach is not a magnitude.

    A refusal that names the recipes beats a plausible number: the whole reason
    the derivation is exact is that a rate which lies sizes a belt wrong.
    """
    loop = _column("loop", {"x": Fraction(2)}, {"x": Fraction(3)})
    with pytest.raises(InfeasibleError, match="loop"):
        _exact_rates([loop], [1.0], ["x"], {"x": Fraction(50)})


def test_required_sub_tolerance_flow_is_recovered_exactly() -> None:
    column = _column("tiny", {}, {"x": Fraction(1)})
    demand = Fraction(1, 10**12)

    crafts = _exact_continuous_rates(
        [column],
        [float(demand)],
        ["x"],
        {"x": demand},
    )

    assert crafts == [demand]


def test_every_material_lp_support_column_remains_a_physical_group() -> None:
    columns = [
        _column("first", {}, {"x": Fraction(1)}),
        _column("second", {}, {"x": Fraction(1)}),
    ]

    crafts = _exact_continuous_rates(
        columns,
        [0.5, 0.5],
        ["x"],
        {"x": Fraction(1)},
    )

    assert all(rate > 0 for rate in crafts)
    assert sum(crafts, Fraction()) == Fraction(1)


def test_no_machines_means_no_rates() -> None:
    loop = _column("loop", {"x": Fraction(2)}, {"x": Fraction(3)})
    assert _exact_rates([loop], [0.0], ["x"], {"x": Fraction(1)}) == [Fraction(0)]


# --- continuous production solve ------------------------------------------


def test_continuous_default_recovers_exact_rates_then_ceils_capacity(
    data: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_milp(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the default production solve must not invoke the MILP oracle")

    monkeypatch.setattr(solve_module, "_run_milp", reject_milp)
    solution = solve(data, parse_url(LOW_RATE_URL))

    assert solution.outputs["magnetic-coil"] == Fraction(1, 60)
    assert solution.groups
    assert any(group.exact_machines < 1 for group in solution.groups)
    for group in solution.groups:
        exact = group.crafts_per_second / group.adjusted.crafts_per_second
        expected = -((-exact.numerator) // exact.denominator)
        assert group.exact_machines == exact
        assert group.machines == expected
        assert group.crafts_per_second <= group.machines * group.adjusted.crafts_per_second

    produced: dict[str, Fraction] = {}
    consumed: dict[str, Fraction] = {}
    for group in solution.groups:
        for item_id, rate in group.outputs.items():
            produced[item_id] = produced.get(item_id, Fraction()) + rate
        for item_id, rate in group.inputs.items():
            consumed[item_id] = consumed.get(item_id, Fraction()) + rate
    for item_id in set(produced) & set(consumed):
        assert produced[item_id] >= consumed[item_id]


def test_continuous_default_uses_the_expected_fractional_route(data: Dataset) -> None:
    solution = solve(
        data,
        parse_url(CONTINUOUS_ROUTE_URL),
        tier=ProliferatorTier.MK2,
    )
    recipes = {group.recipe_id for group in solution.groups}
    assert recipes == CONTINUOUS_ROUTE_RECIPES
    assert len(solution.groups) == 25
    assert solution.machine_count == 25
    assert solution.total_area == 391
    assert solution.outputs["space-warper"] == Fraction(1, 60)
    assert {group.mode for group in solution.groups} == {ProliferatorMode.NONE}
    assert all(
        group.crafts_per_second <= group.machines * group.adjusted.crafts_per_second
        for group in solution.groups
    )


def test_unrecoverable_continuous_pass_falls_back_to_fixed_charge(
    data: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_continuous(*_args: object, **_kwargs: object) -> object:
        raise InfeasibleError("unrecoverable support")

    monkeypatch.setattr(
        solve_module,
        "_run_continuous_lp",
        reject_continuous,
    )
    solution = solve(data, parse_url(LOW_RATE_URL))

    assert solution.outputs["magnetic-coil"] == Fraction(1, 60)
    assert all(
        group.crafts_per_second <= group.machines * group.adjusted.crafts_per_second
        for group in solution.groups
    )



def test_prove_minimal_explicitly_uses_the_fixed_charge_oracle(
    data: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = solve_module._run_milp
    calls = 0

    def recording_milp(
        columns: Sequence[AdjustedRecipe],
        internal_items: Sequence[str],
        demand: Mapping[str, Fraction],
        *,
        time_limit_s: float,
    ) -> tuple[list[float], list[float]]:
        nonlocal calls
        calls += 1
        return original(
            columns,
            internal_items,
            demand,
            time_limit_s=time_limit_s,
        )

    monkeypatch.setattr(solve_module, "_run_milp", recording_milp)
    _ = solve(data, parse_url(LOW_RATE_URL), prove_minimal=True)

    assert calls == 1


# --- hitting the clock is not the same as being infeasible -----------------


TRIVIAL_URL = (
    "https://factoriolab.github.io/dsp/list?o=magnetic-coil*60&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
)


def test_a_starved_solve_warns_and_still_builds(
    data: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A feasible-but-unproven plan is a factory, and must not be thrown away.

    The MILP chooses only STRUCTURE -- the balances are solved exactly
    downstream -- so a feasible structure is a real, buildable factory that
    merely might not be the smallest. Raising discarded the whole build in
    exchange for a proof we do not need. ``universe-matrix`` sat right on the
    edge, ~25s of a 30s budget, and tipped over under load: a timer reported
    as an infeasible spec.

    It warns rather than passing quietly, and the size of the gap is why.
    Measured on ``universe-matrix`` starved to 0.1s: 303 machines against a
    proved-minimal 201. Shipping something 50% larger is exactly the kind of
    thing that goes unnoticed and then becomes the baseline.

    Provoked by relabelling the status rather than by actually starving a
    solver, so this is instant and, more importantly, not a race: a real
    0.1s budget is only reliably short on a machine as slow as today's.
    """
    monkeypatch.setattr(pywraplp.Solver, "FEASIBLE", pywraplp.Solver.OPTIMAL)

    with pytest.warns(RuntimeWarning, match="feasible but unproven-minimal"):
        solution = solve(
            data,
            parse_url(TRIVIAL_URL),
            tier=ProliferatorTier.MK3,
            prove_minimal=True,
        )

    # Valid, not merely non-empty: real counts, and rates still exact.
    assert solution.groups
    assert all(g.machines >= 1 for g in solution.groups)
    assert all(isinstance(g.crafts_per_second, Fraction) for g in solution.groups)


def test_a_solve_that_returns_nothing_usable_still_raises(
    data: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The distinction that makes accepting the timeout safe.

    Accepting FEASIBLE must not slide into accepting any status at all. With
    no status the solver can return counting as usable, there is nothing valid
    to hand back, and that still raises.
    """
    monkeypatch.setattr(pywraplp.Solver, "OPTIMAL", 98)
    monkeypatch.setattr(pywraplp.Solver, "FEASIBLE", 99)

    with pytest.raises(InfeasibleError, match="did not reach optimality"):
        solve(
            data,
            parse_url(TRIVIAL_URL),
            tier=ProliferatorTier.MK3,
            prove_minimal=True,
        )


# --- the player's recipe choices are the player's ---------------------------


REX_URL = (
    "https://factoriolab.github.io/dsp/flow?z=eJxFyLsKwkAQQNG.meJWs8FHNc0sxk6MoLitmkLiEggo2sy3"
    "iyjYHc5oykJlND8zmyukj19.L2n0xwPNd3ujlWqOSrWCyvXUm8vUP21L4cLAHd.ge.yID-E3cht5Te4i76TWyUp4"
    "rKKTh6X0BpZLI18_&v=11"
)


def test_a_urls_exclusion_set_is_authoritative(data: Dataset) -> None:
    """The URL carries the WHOLE set, not a delta against the mod's defaults.

    Proof it is not a delta: this URL lists ``gas-giant-deuterium`` and
    ``gas-giant-hydrogen``, which are NOT in the defaults, while omitting
    ``graphene-advanced`` and ``ice-giant``, which are. A delta would not need
    to restate the twelve it shares.

    This used to union the defaults on top, which silently re-disabled every
    recipe the player had turned ON. Downstream that removed the fire-ice route
    to graphene and left only the sulfuric-acid one, so the build asked the
    player to belt in STONE for a flow containing none -- changing the
    blueprint's inputs, which may never happen.
    """
    request = parse_url(REX_URL)
    assert request.excluded_recipe_ids is not None
    assert _excluded_recipes(data, request) == frozenset(request.excluded_recipe_ids)

    enabled = set(data.default_recipe_excluded) - set(request.excluded_recipe_ids)
    assert enabled, "this URL must differ from the defaults or it proves nothing"
    assert not (enabled & _excluded_recipes(data, request)), (
        f"recipes the player enabled were re-excluded: {sorted(enabled)}"
    )


def test_a_recipe_the_player_enabled_survives_to_the_solver(data: Dataset) -> None:
    """The second layer: `_buildable_producers` must not re-apply the defaults.

    A fix to `_excluded_recipes` alone was not enough -- the player's set
    reached that function intact and was overruled one call deeper, because
    `craftable_recipes_producing` drops the dataset defaults internally.
    """
    request = parse_url(REX_URL)
    excluded = _excluded_recipes(data, request)
    routes = {r.id for r in _buildable_producers(data, "graphene", excluded)}

    assert "graphene-advanced" in routes, (
        "the player enabled graphene-advanced (fire ice); it must reach the solver"
    )
    assert "graphene" in routes, "the sulfuric-acid route is not excluded either"


def test_no_exclusion_set_means_the_mods_defaults(data: Dataset) -> None:
    """Absence is not emptiness.

    A URL that says nothing leaves the player on the mod's defaults -- which is
    every URL in the corpus, so this is what keeps them unchanged. An EMPTY set
    is a player who turned everything on, and is honoured as such.
    """
    bare = parse_url(
        "https://factoriolab.github.io/dsp/list?o=processor*60&ibe=conveyor-belt-2"
        "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
    )
    assert bare.excluded_recipe_ids is None
    assert _excluded_recipes(data, bare) == frozenset(data.default_recipe_excluded)
