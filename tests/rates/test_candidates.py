"""The proliferation frontier: several valid builds, priced later by geometry."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.lab.data import load_dataset
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.adjust import ProliferatorTier
from flab2bp.rates.candidates import (
    build_candidates,
    lanes_requiring_split,
    partition_recipes,
    proliferator_from_request,
)
from flab2bp.spec import BuildSpecSet

EXAMPLE_URL = (
    "https://factoriolab.github.io/dsp/flow"
    "?o=super-magnetic-ring*60"
    "&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
    "&mps=proliferator-2-products"
    "&v=11"
)


@pytest.fixture(scope="module")
def data() -> Dataset:
    return load_dataset()


@pytest.fixture(scope="module")
def candidates(data: Dataset) -> BuildSpecSet:
    return build_candidates(data, parse_url(EXAMPLE_URL), tier=ProliferatorTier.MK3)


# --- the partition that drives everything ----------------------------------


def test_free_and_costly_partition(data: Dataset) -> None:
    """Recipes fed entirely from outside can be sprayed for free.

    Their inputs arrive on belts by construction, so a coater costs no direct
    insertion.  Everything else trades a direct-insertable edge for a belt.
    """
    free, costly = partition_recipes(data, parse_url(EXAMPLE_URL))
    assert free == {"iron-ingot", "copper-ingot", "magnet", "energetic-graphite"}
    assert costly == {
        "super-magnetic-ring",
        "electromagnetic-turbine",
        "electric-motor",
        "gear",
        "magnetic-coil",
    }


# --- the frontier ----------------------------------------------------------


def test_default_emits_three_candidates(candidates: BuildSpecSet) -> None:
    assert [c.label for c in candidates.candidates] == [
        "no-proliferator",
        "free-proliferation",
        "max-proliferation",
    ]


def test_free_proliferation_costs_no_direct_insertion(candidates: BuildSpecSet) -> None:
    """The defining property of the candidate expected to win.

    If this is ever non-empty the candidate is misgenerated, and its whole
    reason for existing -- a machine reduction that geometry does not pay for --
    is gone.
    """
    free = next(c for c in candidates.candidates if c.label == "free-proliferation")
    assert free.belt_required_edges == frozenset()
    assert free.is_proliferated


def test_free_proliferation_sprays_only_external_lanes(candidates: BuildSpecSet) -> None:
    free = next(c for c in candidates.candidates if c.label == "free-proliferation")
    assert free.spray_lanes
    assert all(is_external for is_external in free.spray_lanes.values())


def test_free_proliferation_beats_no_proliferator_on_machines(
    candidates: BuildSpecSet,
) -> None:
    baseline = next(c for c in candidates.candidates if c.label == "no-proliferator")
    free = next(c for c in candidates.candidates if c.label == "free-proliferation")
    assert free.machine_count < baseline.machine_count


def test_max_proliferation_belts_its_internal_edges(candidates: BuildSpecSet) -> None:
    spec = next(c for c in candidates.candidates if c.label == "max-proliferation")
    assert spec.belt_required_edges


def test_no_proliferator_candidate_is_unproliferated(candidates: BuildSpecSet) -> None:
    baseline = next(c for c in candidates.candidates if c.label == "no-proliferator")
    assert not baseline.is_proliferated
    assert baseline.belt_required_edges == frozenset()
    assert baseline.spray_lanes == {}


# --- invariants every candidate must hold ---------------------------------


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


def test_this_chain_needs_no_lane_split(candidates: BuildSpecSet) -> None:
    """The example chain happens to need no splits -- but see the test below.

    Every consumer of its sprayed ore lanes is itself proliferated, so nothing
    has to be cut.  This is a property of *this chain*, not of the approach.
    """
    for spec in candidates.candidates:
        assert spec.lanes_requiring_split == frozenset()


def test_free_proliferation_can_still_need_a_split(data: Dataset) -> None:
    """Splitting is not a rare corner, and free-proliferation is not exempt.

    Scanning all 151 craftable end products, 42 candidates need at least one
    split.  ``electromagnetic-matrix`` is one: ``iron-ore`` feeds both a recipe
    fed purely from outside (proliferated, so its lane is sprayed) and one that
    also takes a manufactured input (not proliferated, so it must not be).
    """
    url = "https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11"
    specs = build_candidates(data, parse_url(url), tier=ProliferatorTier.MK3, count=4)
    free = next(c for c in specs.candidates if c.label == "free-proliferation")
    assert free.lanes_requiring_split == frozenset({"iron-ore"})


def test_max_proliferation_can_need_a_split(data: Dataset) -> None:
    """Even with everything proliferable proliferated, splits still arise.

    A recipe outside the products whitelist that also cannot take speed mode
    profitably stays unproliferated, and any lane it shares gets cut.
    """
    url = "https://factoriolab.github.io/dsp/flow?o=conveyor-belt-3*60&v=11"
    specs = build_candidates(data, parse_url(url), tier=ProliferatorTier.MK3, count=4)
    spec = next(c for c in specs.candidates if c.label == "max-proliferation")
    assert spec.lanes_requiring_split == frozenset({"electromagnetic-turbine"})


def test_split_lanes_are_always_a_subset_of_sprayed_lanes(data: Dataset) -> None:
    """Only a sprayed lane can need splitting; an unsprayed one has nothing to cut."""
    for target in ("electromagnetic-matrix", "conveyor-belt-3", "processor"):
        url = f"https://factoriolab.github.io/dsp/flow?o={target}*60&v=11"
        specs = build_candidates(data, parse_url(url), tier=ProliferatorTier.MK3, count=4)
        for spec in specs.candidates:
            assert spec.lanes_requiring_split <= frozenset(spec.spray_lanes)


def test_unproliferated_candidate_never_needs_a_split(data: Dataset) -> None:
    """With nothing sprayed there is no boundary for a lane to straddle."""
    for target in ("electromagnetic-matrix", "conveyor-belt-3"):
        url = f"https://factoriolab.github.io/dsp/flow?o={target}*60&v=11"
        specs = build_candidates(data, parse_url(url), tier=ProliferatorTier.MK3, count=4)
        baseline = next(c for c in specs.candidates if c.label == "no-proliferator")
        assert baseline.lanes_requiring_split == frozenset()


# --- knobs -----------------------------------------------------------------


def test_candidate_count_can_be_raised(data: Dataset) -> None:
    specs = build_candidates(
        data, parse_url(EXAMPLE_URL), tier=ProliferatorTier.MK3, count=4
    )
    assert len(specs.candidates) == 4
    assert "all-speed-mode" in {c.label for c in specs.candidates}


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
    labels = [s.label for s in specs]
    assert labels == ["no-proliferator", "free-proliferation", "max-proliferation"]
    sprayed = {k for s in specs for k in s.external_inputs if k.startswith("proliferator-")}
    assert sprayed == {"proliferator-3"}, sprayed


def test_an_explicit_tier_still_overrides_the_url(data: Dataset) -> None:
    """The argument wins, so callers that know better are not second-guessed."""
    specs = build_candidates(
        data, parse_url(BARE_MK2), tier=ProliferatorTier.MK3, count=3
    ).candidates
    sprayed = {k for s in specs for k in s.external_inputs if k.startswith("proliferator-")}
    assert sprayed == {"proliferator-3"}, sprayed
