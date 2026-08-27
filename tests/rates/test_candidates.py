"""The proliferation frontier: several valid builds, priced later by geometry."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.lab.data import load_dataset
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.adjust import ProliferatorTier, available_modes, machine_footprint
from flab2bp.rates.candidates import (
    build_candidates,
    lanes_requiring_split,
    proliferator_from_request,
)
from flab2bp.spec import BuildSpecSet, ProliferatorMode

EXAMPLE_URL = (
    "https://factoriolab.github.io/dsp/flow"
    "?o=super-magnetic-ring*60"
    "&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
    "&mps=proliferator-2-products"
    "&v=11"
)

DIAGNOSED_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxFyrEKwkAURNG.ecVUu0GxmmYWYyeJoLituojEJRBQ"
    "tHnfLqJod7jckTrbSB0xmwcgvv38e4EmfLlD8zsy4icXorVKIVhlRrDLoVA2lQc7ZJww4AatoS20h"
    "wbXFan1tELqPW2s1onZ5Uvv7c4YXwAUJfU_&v=11"
)
BROKE_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxFyrEKwkAUBdG.2WKqbFCsXnMXtRMjJLitGkRiCE"
    "QUbd63i2C0OwwzmM5hMB2ZzQuIH7.-XlAWXzaUvyMTpyxNvhxaUxjbp23JnOi4ow2q0R51riu"
    "6kVae1qTK0y70.WjZ5UuvwsNifAOtdSVD&v=11"
)


def test_coproduct_hydrogen_is_internally_balanced_by_buffered_recipe(
    data: Dataset,
) -> None:
    specs = build_candidates(data, parse_url(BROKE_URL)).candidates

    for spec in specs:
        advanced = next(group for group in spec.groups if group.recipe_id == "graphene-advanced")
        consumed = sum(
            group.inputs_per_machine.get("hydrogen", Fraction()) * group.count
            for group in spec.groups
        )
        produced = advanced.outputs_per_machine["hydrogen"] * advanced.count
        assert consumed > 0
        assert produced == consumed
        assert "hydrogen" not in spec.external_inputs
        proof = next(p for p in spec.coproduct_buffer_proofs if p.item_id == "hydrogen")
        assert proof.producer_recipe_id == "graphene-advanced"
        assert proof.consumer_recipe_id == "deuterium"
        assert proof.producer_batch == 1
        assert proof.consumer_batch == 10
        assert proof.required_capacity == 10
        assert proof.intrinsic_capacity == 20
        graphene_produced = (
            advanced.outputs_per_machine["graphene"] * advanced.count
        )
        graphene_consumed = sum(
            group.inputs_per_machine.get("graphene", Fraction()) * group.count
            for group in spec.groups
        )
        assert graphene_produced > graphene_consumed
        assert "graphene" not in spec.outputs
        assert spec.surplus_outputs["graphene"] == graphene_produced - graphene_consumed


@pytest.fixture(scope="module")
def data() -> Dataset:
    return load_dataset()


@pytest.fixture(scope="module")
def candidates(data: Dataset) -> BuildSpecSet:
    return build_candidates(data, parse_url(EXAMPLE_URL), tier=ProliferatorTier.MK3)


# --- the frontier ----------------------------------------------------------


def test_default_emits_three_deterministic_candidates_ranked_by_rounded_area(
    candidates: BuildSpecSet,
) -> None:
    assert {candidate.label for candidate in candidates.candidates} == {
        "no-proliferator",
        "all-products",
        "output-products",
    }
    rounded_areas = [
        sum(
            machine_footprint(group.machine_item_id) * group.count
            for group in candidate.groups
        )
        for candidate in candidates.candidates
    ]
    assert rounded_areas == sorted(rounded_areas)


def test_all_products_uses_products_everywhere_it_is_legal(
    candidates: BuildSpecSet, data: Dataset
) -> None:
    spec = next(
        candidate for candidate in candidates.candidates if candidate.label == "all-products"
    )
    for group in spec.groups:
        legal = available_modes(data, data.recipe(group.recipe_id), ProliferatorTier.MK3)
        expected = (
            ProliferatorMode.PRODUCTS
            if ProliferatorMode.PRODUCTS in legal
            else ProliferatorMode.NONE
        )
        assert group.proliferator_mode is expected


def test_output_products_sprays_only_final_output_recipes(candidates: BuildSpecSet) -> None:
    spec = next(
        candidate for candidate in candidates.candidates if candidate.label == "output-products"
    )
    assert {
        group.recipe_id for group in spec.groups if group.is_proliferated
    } == {"super-magnetic-ring"}
    assert {
        group.proliferator_mode for group in spec.groups if group.is_proliferated
    } == {ProliferatorMode.PRODUCTS}


def test_no_proliferator_candidate_is_unproliferated(candidates: BuildSpecSet) -> None:
    baseline = next(
        candidate
        for candidate in candidates.candidates
        if candidate.label == "no-proliferator"
    )
    assert not baseline.is_proliferated
    assert baseline.belt_required_edges == frozenset()
    assert baseline.spray_lanes == {}


# --- invariants every candidate must hold ---------------------------------

def test_diagnosed_url_has_exact_fixed_policy_counts_and_rates(data: Dataset) -> None:
    specs = build_candidates(data, parse_url(DIAGNOSED_URL)).candidates

    assert {spec.label: spec.machine_count for spec in specs} == {
        "no-proliferator": 13,
        "all-products": 13,
        "output-products": 13,
    }
    assert {
        spec.label: sum(
            machine_footprint(group.machine_item_id) * group.count
            for group in spec.groups
        )
        for spec in specs
    } == {
        "no-proliferator": 215,
        "all-products": 215,
        "output-products": 215,
    }
    assert all(dict(spec.outputs) == {"space-warper": Fraction(1, 60)} for spec in specs)
    assert {spec.label: dict(spec.surplus_outputs) for spec in specs} == {
        "no-proliferator": {"graphene": Fraction(3, 5)},
        "all-products": {"graphene": Fraction(1375, 3888)},
        "output-products": {"graphene": Fraction(1, 2)},
    }


def test_every_proliferated_recipe_declares_its_internal_edges(
    candidates: BuildSpecSet, data: Dataset
) -> None:
    """Invariant 7, and the one whose violation is invisible until runtime.

    A proliferated recipe whose internal input edge is missing here may be
    direct-inserted by the layout stage, which means the machine silently runs
    on unsprayed inputs and under-produces.
    """
    for spec in candidates.candidates:
        made_by = {g.recipe_id: g.recipe_id for g in spec.groups}
        for group in spec.groups:
            if not group.is_proliferated:
                continue
            for item_id in data.recipe(group.recipe_id).inputs:
                producer = made_by.get(item_id)
                if producer is None:
                    continue  # belted in from outside
                assert (producer, group.recipe_id) in spec.belt_required_edges


def test_all_candidates_meet_the_same_objective(candidates: BuildSpecSet) -> None:
    targets = [dict(c.outputs) for c in candidates.candidates]
    for other in targets[1:]:
        assert other.keys() == targets[0].keys()
        for item_id in targets[0]:
            assert other[item_id] >= Fraction(1)


def test_every_candidate_has_no_dangling_demand(candidates: BuildSpecSet) -> None:
    for spec in candidates.candidates:
        produced: dict[str, Fraction] = {}
        consumed: dict[str, Fraction] = {}
        for group in spec.groups:
            for item_id, rate in group.outputs_per_machine.items():
                produced[item_id] = produced.get(item_id, Fraction(0)) + rate * group.count
            for item_id, rate in group.inputs_per_machine.items():
                consumed[item_id] = consumed.get(item_id, Fraction(0)) + rate * group.count
        for item_id, want in consumed.items():
            have = produced.get(item_id, Fraction(0)) + spec.external_inputs.get(
                item_id, Fraction(0)
            )
            assert have >= want, f"{spec.label}: {item_id} short"


def test_proliferator_is_belted_in_never_built(candidates: BuildSpecSet) -> None:
    for spec in candidates.candidates:
        if not spec.is_proliferated:
            continue
        assert spec.external_inputs.get("proliferator-3", Fraction(0)) > 0
        assert not any(g.recipe_id.startswith("proliferator") for g in spec.groups)


def test_belt_tier_comes_from_the_url(candidates: BuildSpecSet) -> None:
    for spec in candidates.candidates:
        assert spec.belt_item_id == "conveyor-belt-2"
        assert spec.belt_items_per_second == Fraction(12)


def test_all_counts_are_positive_integers(candidates: BuildSpecSet) -> None:
    for spec in candidates.candidates:
        for group in spec.groups:
            assert isinstance(group.count, int)
            assert group.count >= 1


def test_rates_are_exact_fractions(candidates: BuildSpecSet) -> None:
    for spec in candidates.candidates:
        for value in (*spec.external_inputs.values(), *spec.outputs.values()):
            assert isinstance(value, Fraction)


# --- the shared-lane hazard ------------------------------------------------


def test_lane_feeding_mixed_consumers_is_flagged_for_splitting(data: Dataset) -> None:
    """A sprayed lane must not also feed an unproliferated consumer.

    If it does, that consumer receives sprayed inputs it was not costed for and
    over-produces, desynchronising the build from these very numbers.  The lane
    has to be split; this reports which.
    """
    request = parse_url(EXAMPLE_URL)
    specs = build_candidates(data, request, tier=ProliferatorTier.MK3)
    for spec in specs.candidates:
        for item_id in lanes_requiring_split(data, spec):
            assert item_id in spec.spray_lanes


def test_split_field_is_populated_on_every_candidate(data: Dataset) -> None:
    specs = build_candidates(data, parse_url(EXAMPLE_URL), tier=ProliferatorTier.MK3)
    for spec in specs.candidates:
        assert spec.lanes_requiring_split == lanes_requiring_split(data, spec)


def test_explicit_policies_report_their_lane_splits(candidates: BuildSpecSet) -> None:
    assert {
        spec.label: spec.lanes_requiring_split for spec in candidates.candidates
    } == {
        "all-products": frozenset(),
        "output-products": frozenset({"magnet"}),
        "no-proliferator": frozenset(),
    }




def test_split_lanes_are_always_a_subset_of_sprayed_lanes(data: Dataset) -> None:
    """Only a sprayed lane can need splitting; an unsprayed one has nothing to cut."""
    for target in ("electromagnetic-matrix", "conveyor-belt-3", "processor"):
        url = f"https://factoriolab.github.io/dsp/flow?o={target}*60&v=11"
        specs = build_candidates(data, parse_url(url), tier=ProliferatorTier.MK3, count=3)
        for spec in specs.candidates:
            assert spec.lanes_requiring_split <= frozenset(spec.spray_lanes)


def test_unproliferated_candidate_never_needs_a_split(data: Dataset) -> None:
    """With nothing sprayed there is no boundary for a lane to straddle."""
    for target in ("electromagnetic-matrix", "conveyor-belt-3"):
        url = f"https://factoriolab.github.io/dsp/flow?o={target}*60&v=11"
        specs = build_candidates(data, parse_url(url), tier=ProliferatorTier.MK3, count=3)
        baseline = next(c for c in specs.candidates if c.label == "no-proliferator")
        assert baseline.lanes_requiring_split == frozenset()


# --- knobs -----------------------------------------------------------------


def test_candidate_count_rejects_removed_speed_policy(data: Dataset) -> None:
    with pytest.raises(ValueError, match="between 1 and 3"):
        _ = build_candidates(
            data,
            parse_url(EXAMPLE_URL),
            tier=ProliferatorTier.MK3,
            count=4,
        )


def test_tier_none_yields_a_single_unproliferated_candidate(data: Dataset) -> None:
    specs = build_candidates(data, parse_url(EXAMPLE_URL), tier=ProliferatorTier.NONE)
    assert len(specs.candidates) == 1
    assert not specs.candidates[0].is_proliferated


# --- the URL's proliferator tier is a constraint, not a suggestion ----------


BARE_MK2 = EXAMPLE_URL  # bare form: the tier arrives in `mps=`.

#: The same request written the way FactorioLab's share button writes it. Here
#: the tier arrives in `modules` and in each machine's own `modules` instead --
#: reading only one of the two forms fixes half the URLs and looks like a fix.
COMPRESSED_MK2 = (
    "https://factoriolab.github.io/dsp/list?z=eJw1xrEKwkAQBNC.2WKqPYh208yR2IkJBLxWvULi"
    "EQgo2uy3i4Wveisde7eVuqLbOZB-..xficEaBbfGArf7pVK21TdPKLhhwRM6QjN0hpbQA3mIfEAeI0.W"
    "2sYSij5GezGlL0XsHqc_&v=11"
)

NO_PROLIFERATOR_NAMED = (
    "https://factoriolab.github.io/dsp/list?o=processor*60&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        pytest.param(BARE_MK2, ProliferatorTier.MK2, id="bare-mps"),
        pytest.param(COMPRESSED_MK2, ProliferatorTier.MK2, id="compressed-modules"),
        pytest.param(NO_PROLIFERATOR_NAMED, None, id="named-nowhere"),
    ],
)
def test_the_tier_is_read_from_every_place_a_url_can_carry_it(
    url: str, expected: ProliferatorTier | None
) -> None:
    assert proliferator_from_request(parse_url(url)) is expected


def test_a_url_asking_for_mk2_does_not_get_handed_mk3(data: Dataset) -> None:
    """The sprayed item is belted in, so the tier is an availability statement.

    Spending Mk.III on a player who asked for Mk.II hands them a plan that is
    perfectly valid and that they cannot build, because the blueprint's external
    input belt calls for an item they may not have.  That is a worse failure
    than refusing, since nothing about the output says it happened.
    """
    specs = build_candidates(data, parse_url(BARE_MK2), count=3).candidates
    sprayed = {k for s in specs for k in s.external_inputs if k.startswith("proliferator-")}
    assert sprayed == {"proliferator-2"}, sprayed


def test_a_url_naming_no_proliferator_keeps_the_whole_frontier(data: Dataset) -> None:
    """Absence is not a constraint.

    Most URLs never mention proliferation, and reading that as "no proliferator"
    would collapse the frontier to a single candidate and discard the density
    this tool exists to find.
    """
    specs = build_candidates(data, parse_url(NO_PROLIFERATOR_NAMED), count=3).candidates
    labels = {spec.label for spec in specs}
    assert labels == {"no-proliferator", "all-products", "output-products"}
    sprayed = {k for s in specs for k in s.external_inputs if k.startswith("proliferator-")}
    assert sprayed == {"proliferator-3"}, sprayed


def test_an_explicit_tier_still_overrides_the_url(data: Dataset) -> None:
    """The argument wins, so callers that know better are not second-guessed."""
    specs = build_candidates(
        data, parse_url(BARE_MK2), tier=ProliferatorTier.MK3, count=3
    ).candidates
    sprayed = {k for s in specs for k in s.external_inputs if k.startswith("proliferator-")}
    assert sprayed == {"proliferator-3"}, sprayed
