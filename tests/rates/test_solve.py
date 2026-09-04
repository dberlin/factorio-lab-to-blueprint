"""The production solve: objectives in, exact machine counts out."""

from __future__ import annotations

import importlib
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import replace
from fractions import Fraction
from typing import Protocol, TypeGuard

import pytest
from ortools.linear_solver import pywraplp  # type: ignore[import-untyped]

from flab2bp.lab.data import load_dataset
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import LabRequest, Objective, ObjectiveType, ObjectiveUnit, parse_url
from flab2bp.rates.adjust import AdjustedRecipe, ProliferatorTier
from flab2bp.rates.solve import (
    InfeasibleError,
    RateSolution,
    _buildable_producers,
    _exact_continuous_rates,
    _exact_rates,
    _excluded_recipes,
    solve,
    supplied_rates,
    target_rates,
)
from flab2bp.spec import ProliferatorMode


class _ContinuousLp(Protocol):
    def __call__(
        self,
        columns: Sequence[AdjustedRecipe],
        internal_items: Sequence[str],
        demand: Mapping[str, Fraction],
        *,
        objective: object | None = None,
        time_limit_s: float,
    ) -> list[float]: ...


class _Milp(Protocol):
    def __call__(
        self,
        columns: Sequence[AdjustedRecipe],
        internal_items: Sequence[str],
        demand: Mapping[str, Fraction],
        *,
        objective: object | None = None,
        time_limit_s: float,
    ) -> tuple[list[float], list[float]]: ...


class _SolveModule(Protocol):
    _run_continuous_lp: _ContinuousLp
    _run_milp: _Milp


def _is_solve_module(module: object) -> TypeGuard[_SolveModule]:
    return callable(getattr(module, "_run_continuous_lp", None)) and callable(
        getattr(module, "_run_milp", None)
    )


def _load_solve_module() -> _SolveModule:
    module: object = importlib.import_module("flab2bp.rates.solve")
    if not _is_solve_module(module):
        raise RuntimeError("flab2bp.rates.solve lacks its solver seams")
    return module


solve_module = _load_solve_module()

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
#: Re-derived under extraction pricing (design). Previously 25 recipes
#: including ``organic-crystal`` and ``plastic``: the structural cut treated
#: organic crystal's vein as automatically external only when NO crafting
#: recipe existed, so it was crafted from plastic and other inputs. Priced,
#: FactorioLab's own cheap vein wins instead, and plastic -- which nothing
#: else in this chain needs -- drops out entirely rather than becoming a
#: belt-in input.  ``organic-crystal`` itself still shows up, now as a
#: belt-in (``external_inputs``) rather than a machine.
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
        "particle-container",
        "plane-filter",
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
        g.machine_item_id in {"mining-machine", "oil-extractor", "water-pump"} for g in plain.groups
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


def test_machine_counts_are_exact_not_snapped_floats(data: Dataset, plain: RateSolution) -> None:
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
        group.crafts_per_second <= group.machines * group.adjusted.crafts_per_second
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


COST_URL = (
    "https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60"
    "&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
    "&mps=proliferator-2-products&cfa=100&cma=100&cfp=100&csu=100&v=11"
)


def test_omitted_costs_match_factoriolab_defaults(
    data: Dataset,
    plain: RateSolution,
) -> None:
    explicit_defaults = EXAMPLE_URL.replace(
        "&v=11",
        "&cfa=1&cma=1&cfp=1&csu=0&v=11",
    )

    assert solve(data, parse_url(explicit_defaults)) == plain


def test_surplus_cost_reaches_downstream_coproduct_consumers(
    data: Dataset,
) -> None:
    request = parse_url(
        "https://factoriolab.github.io/dsp/flow?o=antimatter*60&cma=0&cfp=0&csu=1&v=11"
    )

    result = solve(data, request, prove_minimal=False)

    assert sum(result.surplus.values(), Fraction()) < 1


def test_factoriolab_costs_weight_machine_footprint_and_surplus(
    data: Dataset,
) -> None:
    from flab2bp.rates.solve import (
        _columns,
        _objective_coefficients,
        _resolve_chain,
    )

    request = parse_url(COST_URL)
    targets = target_rates(data, request)
    excluded = _excluded_recipes(data, request)
    producers, _external = _resolve_chain(data, targets, excluded)
    columns = _columns(
        data,
        producers,
        request,
        ProliferatorTier.NONE,
        None,
        None,
    )
    coefficients = _objective_coefficients(data, request, columns)
    index = next(i for i, column in enumerate(columns) if column.recipe_id == "super-magnetic-ring")
    column = columns[index]

    # cma=100 and cfp=100, but ``adjustCosts`` applies the footprint factor
    # only to a machine whose dataset entry declares a ``size``, and no DSP
    # machine does -- so the footprint cost is inert here and the machine
    # cost is exactly ``costs.machine``, never our catalog footprint.
    assert data.machine(column.machine_item_id).size is None
    assert coefficients.machine[index] == 100
    net_items = sum(
        (
            column.outputs_per_craft.get(item_id, Fraction())
            - column.inputs_per_craft.get(item_id, Fraction())
            for item_id in coefficients.items
        ),
        Fraction(),
    )
    assert coefficients.surplus[index] == 100 * net_items
    assert coefficients.continuous[index] == (
        coefficients.machine[index] / column.crafts_per_second + coefficients.surplus[index]
    )


def test_factoriolab_recipe_factor_scales_declared_recipe_cost(
    data: Dataset,
) -> None:
    from flab2bp.rates.adjust import adjust, select_machine
    from flab2bp.rates.solve import _objective_coefficients

    request = parse_url("https://factoriolab.github.io/dsp/flow?o=antimatter*1&cfa=100&v=11")
    recipe = data.recipe("mass-energy-storage")
    column = adjust(
        data,
        recipe,
        select_machine(data, recipe, request.machine_rank_ids),
    )
    coefficients = _objective_coefficients(data, request, [column])

    assert recipe.cost is not None
    assert coefficients.machine == (
        sum(column.outputs_per_craft.values(), Fraction())
        * column.crafts_per_second
        * recipe.cost
        * 100,
    )


def test_derivation_ignores_solver_float_noise(data: Dataset) -> None:
    """The derivation must depend on the solver's structure, never its floats.

    Perturbing the reported machine counts by float noise -- the kind a solver
    genuinely returns, ``3.9999999997`` for 4 -- must not move the derived rates
    at all.  A derivation that reads magnitudes out of the solver fails this;
    one that reads only ``round(n)`` and propagates demand exactly cannot.

    EXAMPLE_URL's ore now resolves to extraction columns:
    ``solve(...).groups`` never includes them (they are never a ``SolvedGroup``),
    so the raw machine value this test hands ``_exact_rates`` for each of them
    is set directly to ``1.0`` rather than read off ``counts`` -- any positive
    value works, since an extraction column is uncapped and merely needs to
    clear the support tolerance, and the exact LP needs their ore supply
    present or it has nothing to balance the crafting chain against.  The
    noise/fuzz perturbation and its assertions stay on the crafting counts.
    """
    from flab2bp.rates.solve import _columns, _exact_rates, _ExtractionColumn, _resolve_chain

    request = parse_url(EXAMPLE_URL)
    targets = target_rates(data, request)
    excluded = frozenset(request.excluded_recipe_ids or ()) | data.default_recipe_excluded
    producers, _external = _resolve_chain(data, targets, excluded)
    internal = sorted(producers)
    columns = _columns(data, producers, request, ProliferatorTier.NONE, None, None)

    counts = {g.recipe_id: g.machines for g in solve(data, request).groups}
    clean = [
        1.0 if isinstance(column, _ExtractionColumn) else float(counts.get(column.recipe_id, 0))
        for column in columns
    ]
    # Perturb well beyond float noise but strictly inside the rounding
    # interval, so `round(n)` is unmoved while every *magnitude* shifts.  A
    # derivation reading magnitudes out of the solver changes its answer here;
    # one reading only the rounded count cannot.  Extraction entries stay
    # comfortably positive under either perturbation, since they carry no cap
    # to round against.
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
            f"{group.recipe_id}: {group.machines} machines against an exact requirement of {exact}"
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
        "plasma-refining",
        {"crude": Fraction(2)},
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
        "plasma-refining",
        {"crude": Fraction(2)},
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


# --- production oracle and continuous opt-out -----------------------------


def test_explicit_continuous_path_recovers_exact_rates_then_ceils_capacity(
    data: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_milp(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the explicit continuous solve must not invoke the MILP oracle")

    monkeypatch.setattr(solve_module, "_run_milp", reject_milp)
    solution = solve(data, parse_url(LOW_RATE_URL), prove_minimal=False)

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


def test_explicit_continuous_path_uses_the_expected_fractional_route(
    data: Dataset,
) -> None:
    """Re-derived under extraction pricing (design): 23 machines, not 25.

    FactorioLab's own flow for this URL runs ``space-warper-advanced`` (the
    gravity-matrix route) and ``graphene-advanced``, both still here.  The
    machine count fell from 25 to 23 and the footprint from 391 to 321 tiles
    because ``organic-crystal`` is now belted in from its vein rather than
    crafted from plastic, dropping both recipes (and everything plastic alone
    fed) out of the structure entirely -- see ``CONTINUOUS_ROUTE_RECIPES``.
    """
    solution = solve(
        data,
        parse_url(CONTINUOUS_ROUTE_URL),
        tier=ProliferatorTier.MK2,
        prove_minimal=False,
    )
    recipes = {group.recipe_id for group in solution.groups}
    assert recipes == CONTINUOUS_ROUTE_RECIPES
    assert len(solution.groups) == 23
    assert solution.machine_count == 23
    assert solution.total_area == 321
    assert solution.outputs["space-warper"] == Fraction(1, 60)
    assert {group.mode for group in solution.groups} == {ProliferatorMode.NONE}
    assert all(
        group.crafts_per_second <= group.machines * group.adjusted.crafts_per_second
        for group in solution.groups
    )
    assert "organic-crystal" in solution.external_inputs


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
    solution = solve(data, parse_url(LOW_RATE_URL), prove_minimal=False)

    assert solution.outputs["magnetic-coil"] == Fraction(1, 60)
    assert all(
        group.crafts_per_second <= group.machines * group.adjusted.crafts_per_second
        for group in solution.groups
    )


def test_default_solve_uses_the_fixed_charge_oracle(
    data: Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = solve_module._run_milp
    calls = 0

    def recording_milp(
        columns: Sequence[AdjustedRecipe],
        internal_items: Sequence[str],
        demand: Mapping[str, Fraction],
        *,
        objective: object | None = None,
        time_limit_s: float,
    ) -> tuple[list[float], list[float]]:
        nonlocal calls
        calls += 1
        return original(
            columns,
            internal_items,
            demand,
            objective=objective,
            time_limit_s=time_limit_s,
        )

    monkeypatch.setattr(solve_module, "_run_milp", recording_milp)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _ = solve(data, parse_url(LOW_RATE_URL))

    assert calls == 1
    assert not any("feasible but unproven-minimal" in str(item.message) for item in caught)


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


# --- what FactorioLab extracts, we belt in ----------------------------------


#: A reported URL: deuteron fuel rods with a hand-picked exclusion set that
#: turns OFF the gas-giant collectors and fire-ice veins but leaves
#: ``ice-giant-hydrogen`` and ``graphene-advanced`` ON.  FactorioLab's own flow
#: for it runs ``ice-giant-hydrogen`` x16.7 and ``sulphuric-acid-vein`` x2.4 and
#: belts hydrogen and sulfuric acid in; it never touches fire ice.
COLLECTOR_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNzD0LwjAYBOB.k-GmJGKd3uWCuokVFLNaO2gthfqBOry."
    "XSrGdHvu4K6TCOet6YQVnLWAG3weOWbP4O2.JybJOxSjqU--ZbKCnya.8pIc3n.hjeKr06GWYPr6KWtEHNHgDq7ALbgHG-"
    "UFvCIsNCwRSg0b07a9RKXOtTQPce4DLu01vA__&v=11"
)

GRAPHENE_CORPUS_URL = (
    "https://factoriolab.github.io/dsp/list?o=graphene*60&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
)


def test_an_item_with_an_enabled_extraction_recipe_is_belted_in(data: Dataset) -> None:
    """Hydrogen has a collector recipe the player left on, so it is an input.

    The old rule made an item internal whenever ANY non-mining recipe could
    produce it, so hydrogen was crafted through ``graphene-advanced`` -- 80
    chemical plants eating 80 fire ice/s to make 40 hydrogen/s, with 80
    graphene/s falling out as surplus -- and sulfuric acid through stone, water
    and refined oil.  FactorioLab's flow for this URL does neither: with
    ``ice-giant-hydrogen`` and ``sulphuric-acid-vein`` enabled, both items are
    collected outside and arrive on a belt.  This is the outcome of pricing,
    not a rule that an extractable item is never crafted: on the space-warper
    URL below hydrogen has enabled collectors and part of it is still made as
    ``graphene-advanced``'s coproduct, because that route is cheaper overall.
    """
    request = parse_url(COLLECTOR_URL)
    assert request.excluded_recipe_ids is not None
    assert "ice-giant-hydrogen" not in request.excluded_recipe_ids
    assert "graphene-advanced" not in request.excluded_recipe_ids

    plan = solve(data, request)

    assert {g.recipe_id: g.machines for g in plan.groups} == {
        "deuterium": 10,
        "deuteron-fuel-rod": 12,
        "titanium-alloy": 3,
    }
    assert plan.external_inputs["hydrogen"] == Fraction(40)
    assert plan.external_inputs["sulfuric-acid"] == Fraction(2)
    assert not {"fire-ice", "stone", "water"} & set(plan.external_inputs)
    assert "graphene" not in plan.surplus


def test_the_graphene_corpus_url_belts_in_sulfuric_acid(data: Dataset) -> None:
    """A URL with no exclusion set sits on the mod's defaults, and those leave
    ``sulphuric-acid-vein`` on.  FactorioLab's flow: graphene x1.5, energetic
    graphite x3, coal 180/min and sulfuric acid 30/min in -- no refinery, no
    stone, no water."""
    plan = solve(data, parse_url(GRAPHENE_CORPUS_URL))

    assert {g.recipe_id: g.machines for g in plan.groups} == {
        "energetic-graphite": 3,
        "graphene": 2,
    }
    assert dict(plan.external_inputs) == {
        "coal": Fraction(3),
        "sulfuric-acid": Fraction(1, 2),
    }


def test_excluding_every_extraction_recipe_restores_the_crafted_route(
    data: Dataset,
) -> None:
    """The exclusion set is the player's lever, in both directions.

    Turn off the last collector that makes hydrogen and the only way left is
    to craft it, so the fire-ice route the player enabled is what gets built.
    """
    request = parse_url(COLLECTOR_URL)
    assert request.excluded_recipe_ids is not None
    request = replace(
        request,
        excluded_recipe_ids=set(request.excluded_recipe_ids) | {"ice-giant-hydrogen", "ice-giant"},
    )

    plan = solve(data, request)

    assert "graphene-advanced" in {g.recipe_id for g in plan.groups}
    assert "hydrogen" not in plan.external_inputs
    assert plan.external_inputs["fire-ice"] > 0


def test_a_requested_output_is_built_even_when_it_could_be_collected(
    data: Dataset,
) -> None:
    """The rule applies to intermediates, not to what the player asked for.

    An Output objective on hydrogen is a request to MAKE hydrogen; a blueprint
    of zero machines would satisfy nobody, so the crafting route stands.
    """
    hydrogen = parse_url(
        "https://factoriolab.github.io/dsp/list?o=hydrogen*60&ibe=conveyor-belt-2"
        "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
    )
    plan = solve(data, hydrogen)

    assert {g.recipe_id for g in plan.groups} == {"plasma-refining"}
    assert plan.outputs["hydrogen"] == Fraction(1)


def test_extraction_prices_pick_factoriolabs_graphene_route(data: Dataset) -> None:
    """Pricing, not a structural cut, is what picks the crafted route here.

    CONTINUOUS_ROUTE_URL's exclusion set leaves ``ice-giant``,
    ``ice-giant-hydrogen``, ``graphene-advanced``, and ``sulphuric-acid-vein``
    all enabled -- both an extraction route and a crafting route are on the
    table for graphene. FactorioLab's own flow for this URL runs
    ``graphene-advanced`` (fed by fire ice and a hydrogen coproduct from
    ``ice-giant``) rather than ``graphene`` (energetic graphite plus sulfuric
    acid): the cheap ``ice-giant`` route undercuts building a sulfuric acid
    vein AND everything sulfuric acid would otherwise drag in. Fire ice and
    hydrogen are never crafted in this dataset, so whichever amount
    ``graphene-advanced`` needs of them shows up as a belt-in input, exactly
    like an ore.
    """
    plan = solve(data, parse_url(CONTINUOUS_ROUTE_URL))

    recipe_ids = {g.recipe_id for g in plan.groups}
    assert "graphene-advanced" in recipe_ids
    assert "graphene" not in recipe_ids
    assert {"fire-ice", "hydrogen"} <= set(plan.external_inputs)
    assert "sulfuric-acid" not in plan.external_inputs


def test_deuterium_is_crafted_from_collected_hydrogen_as_factoriolab_does(
    data: Dataset,
) -> None:
    """A DSP crafting machine costs exactly ``costs.machine`` in FactorioLab.

    ``adjustCosts`` multiplies the machine cost by ``machine.size`` only when
    the dataset declares a size, and the DSP dataset declares none for any of
    its 52 machines.  So five colliders plus 2.6 hydrogen collectors (cost
    about 7.6) beat 31 deuterium collectors (cost 31), and FactorioLab's flow
    for this URL crafts deuterium from collected hydrogen: ``deuterium`` x5,
    ``gas-giant-hydrogen`` x2.6, hydrogen 1200/min in, no deuterium input.
    Weighting crafting machines by our catalog footprint instead flipped that
    and belted deuterium in, changing the blueprint's inputs.
    """
    plan = solve(
        data,
        parse_url(
            "https://factoriolab.github.io/dsp/list?o=deuteron-fuel-rod*60"
            "&ibe=conveyor-belt-2"
            "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
        ),
    )

    machines = {g.recipe_id: g.machines for g in plan.groups}
    assert machines["deuterium"] == 5
    assert plan.external_inputs["hydrogen"] == Fraction(20)
    assert "deuterium" not in plan.external_inputs


# --- the URL's cargo stack on a Belts objective ----------------------------


def _one_belt_of(request: LabRequest, *, type_: ObjectiveType) -> LabRequest:
    objective = Objective(
        id="1",
        target_id="super-magnetic-ring",
        value=Fraction(1),
        unit=ObjectiveUnit.Belts,
        type=type_,
    )
    return replace(request, belt_id="conveyor-belt-3", objectives=(objective,))


@pytest.mark.parametrize(
    ("stack", "expected"),
    (
        (None, 30),  # design rule 1: no `ist` is judged exactly as today
        (Fraction(1), 30),
        (Fraction(2), 60),
        (Fraction(4), 120),
        (Fraction(9), 120),  # never above the game's largest pile
    ),
)
def test_a_belts_objective_counts_cargo_not_items(
    data: Dataset, stack: Fraction | None, expected: int
) -> None:
    """One Mk.III belt is 30 CARGO/s; at ``ist=2`` that is 60 items/s."""
    request = _one_belt_of(parse_url(EXAMPLE_URL), type_=ObjectiveType.Output)
    rates = target_rates(data, replace(request, stack=stack))
    assert rates == {"super-magnetic-ring": Fraction(expected)}


def test_a_belts_input_objective_counts_cargo_too(data: Dataset) -> None:
    """The declared external supply is the same belt, so it stacks the same
    way; leaving this branch unstacked would under-declare the bus."""
    request = _one_belt_of(parse_url(EXAMPLE_URL), type_=ObjectiveType.Input)
    assert supplied_rates(data, request) == {"super-magnetic-ring": Fraction(30)}
    assert supplied_rates(data, replace(request, stack=Fraction(2))) == {
        "super-magnetic-ring": Fraction(60)
    }
