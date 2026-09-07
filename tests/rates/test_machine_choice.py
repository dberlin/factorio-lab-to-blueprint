from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset
from flab2bp.rates.adjust import ProliferatorTier, adjust
from flab2bp.rates.machine_choice import (
    MachineRank,
    candidate_ladder,
    choose_machine,
    machine_speed,
    machines_needed,
)
from flab2bp.spec import ProliferatorMode


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


def test_an_unlocked_unknown_producer_is_not_a_candidate(data) -> None:
    unknown = replace(data.item("arc-smelter"), id="unknown-smelter")
    custom = replace(data, items=(*data.items, unknown))
    recipe = replace(
        data.recipe("iron-ingot"),
        producers=("unknown-smelter", "arc-smelter", "plane-smelter"),
    )
    unlocked = {"unknown-smelter", "arc-smelter", "plane-smelter"}

    assert candidate_ladder(custom, recipe, "plane-smelter", unlocked) == (
        "arc-smelter",
        "plane-smelter",
    )
    assert choose_machine(
        custom,
        recipe,
        ceiling_id="plane-smelter",
        craft_rate=Fraction(1, 2),
        mode=ProliferatorMode.NONE,
        tier=ProliferatorTier.NONE,
        unlocked=unlocked,
    ) == "arc-smelter"


def _choose(data, recipe_id: str, ceiling: str, craft_rate: Fraction) -> str:
    return choose_machine(
        data,
        data.recipe(recipe_id),
        ceiling_id=ceiling,
        craft_rate=craft_rate,
        mode=ProliferatorMode.NONE,
        tier=ProliferatorTier.NONE,
        unlocked=_every_machine(data),
    )


def test_machines_needed_is_an_exact_ceiling() -> None:
    assert machines_needed(Fraction(1, 2), Fraction(1)) == 1
    assert machines_needed(Fraction(5, 2), Fraction(1)) == 3
    assert machines_needed(Fraction(3), Fraction(1)) == 3
    assert machines_needed(Fraction(0), Fraction(1)) == 0
    # 0.1 is not representable in binary floating point; the exact form is.
    assert machines_needed(Fraction(1, 10) * 10, Fraction(1)) == 1


def test_a_rate_only_the_top_smelter_meets_in_one_machine_keeps_it(data) -> None:
    # iron-ingot: time 1s, out 1.  arc 1/s, plane 2/s, negentropy 3/s.
    # 2.4 crafts/s -> arc ceil(2.4)=3, plane ceil(1.2)=2, negentropy ceil(0.8)=1.
    assert _choose(data, "iron-ingot", "negentropy-smelter", Fraction(12, 5)) == (
        "negentropy-smelter"
    )


def test_a_rate_the_bottom_smelter_also_meets_in_one_machine_drops_to_it(data) -> None:
    # 0.5 crafts/s -> every smelter needs ceil(<=0.5) == 1; tie -> lowest tier.
    assert _choose(data, "iron-ingot", "negentropy-smelter", Fraction(1, 2)) == "arc-smelter"


def test_a_tie_between_the_middle_and_the_top_takes_the_middle(data) -> None:
    # 1.5 crafts/s -> arc 2, plane 1, negentropy 1.  Tie between plane and
    # negentropy at 1; the slower one wins.
    assert _choose(data, "iron-ingot", "negentropy-smelter", Fraction(3, 2)) == "plane-smelter"


def test_the_ceiling_bounds_the_choice_from_above(data) -> None:
    # With an arc-smelter ceiling nothing faster may be chosen, even though
    # a faster smelter would need fewer machines.
    assert _choose(data, "iron-ingot", "arc-smelter", Fraction(12, 5)) == "arc-smelter"


def test_a_locked_save_cannot_be_handed_a_machine_it_has_not_researched(data) -> None:
    chosen = choose_machine(
        data,
        data.recipe("iron-ingot"),
        ceiling_id="negentropy-smelter",
        craft_rate=Fraction(1, 2),
        mode=ProliferatorMode.NONE,
        tier=ProliferatorTier.NONE,
        unlocked=frozenset({"plane-smelter"}),
    )
    assert chosen == "plane-smelter"


def test_the_choice_never_needs_more_machines_than_the_ceiling(data) -> None:
    """Invariant U: up-to is exactly count-preserving."""
    every = _every_machine(data)
    checked = 0
    for recipe in data.recipes:
        if len(recipe.producers) < 2:
            continue
        ceiling = recipe.producers[-1]
        if not _is_placeable_for_test(ceiling):
            continue
        for numerator in (1, 2, 3, 5, 7, 11, 23, 97):
            for denominator in (1, 2, 3, 4, 10):
                rate = Fraction(numerator, denominator)
                chosen = choose_machine(
                    data,
                    recipe,
                    ceiling_id=ceiling,
                    craft_rate=rate,
                    mode=ProliferatorMode.NONE,
                    tier=ProliferatorTier.NONE,
                    unlocked=every,
                )
                before = machines_needed(rate, adjust(data, recipe, ceiling).crafts_per_second)
                after = machines_needed(rate, adjust(data, recipe, chosen).crafts_per_second)
                assert after == before, (recipe.id, ceiling, chosen, rate)
                checked += 1
    assert checked > 1000


def _is_placeable_for_test(machine_id: str) -> bool:
    from flab2bp.dsp import catalog

    try:
        return catalog.get_item_id(machine_id) is not None
    except KeyError, ValueError:
        return False
