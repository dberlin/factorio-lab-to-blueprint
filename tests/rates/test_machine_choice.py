from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset
from flab2bp.rates.machine_choice import MachineRank, candidate_ladder, machine_speed


@pytest.fixture(scope="module")
def data():
    return canonicalize_dataset(load_vendored())


def _every_machine(data) -> frozenset[str]:
    return frozenset(item.id for item in data.items if item.machine is not None)


def test_the_mode_values_are_the_cli_spelling() -> None:
    assert MachineRank.EXACT.value == "exact"
    assert MachineRank.UP_TO.value == "up-to"
    assert [m.value for m in MachineRank] == ["exact", "up-to"]


def test_speed_of_a_machine_without_one_is_one(data) -> None:
    assert machine_speed(data, "arc-smelter") == Fraction(1)
    assert machine_speed(data, "plane-smelter") == Fraction(2)
    assert machine_speed(data, "negentropy-smelter") == Fraction(3)
    assert machine_speed(data, "assembling-machine-1") == Fraction(3, 4)


def test_the_ladder_under_the_top_smelter_is_every_smelter_slowest_first(data) -> None:
    recipe = data.recipe("iron-ingot")
    ladder = candidate_ladder(data, recipe, "negentropy-smelter", _every_machine(data))
    assert ladder == ("arc-smelter", "plane-smelter", "negentropy-smelter")


def test_the_ladder_stops_at_the_ceiling(data) -> None:
    recipe = data.recipe("iron-ingot")
    assert candidate_ladder(data, recipe, "plane-smelter", _every_machine(data)) == (
        "arc-smelter",
        "plane-smelter",
    )
    assert candidate_ladder(data, recipe, "arc-smelter", _every_machine(data)) == ("arc-smelter",)


def test_the_ladder_is_ordered_by_speed_then_dataset_order(data) -> None:
    recipe = data.recipe("tesla-tower")
    ladder = candidate_ladder(data, recipe, "re-composing-assembler", _every_machine(data))
    assert ladder == (
        "assembling-machine-1",
        "assembling-machine-2",
        "assembling-machine-3",
        "re-composing-assembler",
    )
    speeds = [machine_speed(data, m) for m in ladder]
    assert speeds == sorted(speeds)


def test_a_locked_machine_is_not_a_candidate(data) -> None:
    recipe = data.recipe("iron-ingot")
    ladder = candidate_ladder(data, recipe, "negentropy-smelter", {"arc-smelter"})
    assert ladder == ("arc-smelter", "negentropy-smelter")


def test_the_ceiling_is_always_admitted_even_when_locked(data) -> None:
    recipe = data.recipe("iron-ingot")
    assert candidate_ladder(data, recipe, "plane-smelter", frozenset()) == ("plane-smelter",)


def test_a_single_producer_recipe_has_a_one_entry_ladder(data) -> None:
    recipe = next(r for r in data.recipes if len(r.producers) == 1)
    ceiling = recipe.producers[0]
    assert candidate_ladder(data, recipe, ceiling, _every_machine(data)) == (ceiling,)


def test_every_ladder_entry_is_placeable(data) -> None:
    from flab2bp.dsp import catalog

    every = _every_machine(data)
    for recipe in data.recipes:
        if len(recipe.producers) < 2:
            continue
        for machine_id in candidate_ladder(data, recipe, recipe.producers[-1], every):
            catalog.get_item_id(machine_id)  # must not raise
