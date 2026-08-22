"""Per-machine recipe arithmetic, mirroring FactorioLab's ``adjustRecipe``."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.lab.data import load_dataset
from flab2bp.lab.schema import Dataset
from flab2bp.rates.adjust import (
    ProliferatorTier,
    adjust,
    available_modes,
    machine_footprint,
    select_machine,
)
from flab2bp.spec import ProliferatorMode

EXAMPLE_RANK = (
    "arc-smelter",
    "assembling-machine-2",
    "chemical-plant",
    "matrix-lab",
)


@pytest.fixture(scope="module")
def data() -> Dataset:
    return load_dataset()


# --- machine selection -----------------------------------------------------


def test_bestmatch_picks_first_ranked_producer(data: Dataset) -> None:
    """``super-magnetic-ring`` lists asm 1/2/3; the rank names asm-2."""
    assert select_machine(data, data.recipe("super-magnetic-ring"), EXAMPLE_RANK) == (
        "assembling-machine-2"
    )


def test_bestmatch_falls_back_to_first_producer(data: Dataset) -> None:
    """A rank naming nothing this recipe can use falls back to producers[0]."""
    recipe = data.recipe("super-magnetic-ring")
    assert select_machine(data, recipe, ("matrix-lab",)) == recipe.producers[0]


def test_assembling_machine_1_is_speed_three_quarters(data: Dataset) -> None:
    """Regression: asm-1 is 0.75, not 1.

    Treating it as 1 makes the example URL's machine-rank swap look like a no-op
    when it is really a 1.33x speedup that changes every assembler count.
    """
    assert data.machine("assembling-machine-1").speed == Fraction(3, 4)
    assert data.machine("assembling-machine-2").speed == Fraction(1)


# --- unproliferated arithmetic ---------------------------------------------


def test_super_magnetic_ring_per_machine_rates(data: Dataset) -> None:
    a = adjust(data, data.recipe("super-magnetic-ring"), "assembling-machine-2")
    assert a.craft_time == Fraction(3)
    assert a.output_rate("super-magnetic-ring") == Fraction(1, 3)
    assert a.input_rate("electromagnetic-turbine") == Fraction(2, 3)
    assert a.input_rate("magnet") == Fraction(1)
    assert a.input_rate("energetic-graphite") == Fraction(1, 3)


def test_multi_output_recipe_rate(data: Dataset) -> None:
    """``magnetic-coil`` yields 2 per craft in 1s, so 2/s per machine."""
    a = adjust(data, data.recipe("magnetic-coil"), "assembling-machine-2")
    assert a.output_rate("magnetic-coil") == Fraction(2)


def test_machine_speed_divides_craft_time(data: Dataset) -> None:
    recipe = data.recipe("super-magnetic-ring")
    slow = adjust(data, recipe, "assembling-machine-1")
    fast = adjust(data, recipe, "assembling-machine-2")
    assert slow.craft_time == Fraction(4)  # 3 / 0.75
    assert fast.craft_time == Fraction(3)


def test_rates_are_exact_fractions(data: Dataset) -> None:
    a = adjust(data, data.recipe("magnet"), "arc-smelter")
    rate = a.output_rate("magnet")
    assert isinstance(rate, Fraction)
    assert rate == Fraction(2, 3)


# --- proliferator ----------------------------------------------------------


def test_speed_mode_halves_craft_time_at_mk3(data: Dataset) -> None:
    """Mk.III speed is +100%, so craft time halves and inputs are untouched."""
    recipe = data.recipe("magnet")
    plain = adjust(data, recipe, "arc-smelter")
    fast = adjust(data, recipe, "arc-smelter", ProliferatorMode.SPEED, ProliferatorTier.MK3)
    assert fast.craft_time == plain.craft_time / 2
    assert fast.output_rate("magnet") == plain.output_rate("magnet") * 2
    # Speed mode does not compound: ore per unit of output is unchanged at 1:1.
    assert fast.input_rate("iron-ore") / fast.output_rate("magnet") == Fraction(1)
    assert plain.input_rate("iron-ore") / plain.output_rate("magnet") == Fraction(1)


def test_products_mode_scales_outputs_but_not_inputs(data: Dataset) -> None:
    """This asymmetry is exactly why products mode compounds up the chain."""
    recipe = data.recipe("magnet")
    plain = adjust(data, recipe, "arc-smelter")
    prod = adjust(data, recipe, "arc-smelter", ProliferatorMode.PRODUCTS, ProliferatorTier.MK3)
    assert prod.craft_time == plain.craft_time
    assert prod.outputs_per_craft["magnet"] == Fraction(5, 4)  # 1 * 1.25
    assert prod.inputs_per_craft["iron-ore"] == Fraction(1)  # unchanged
    # Less ore per unit of output -- the compounding effect.  1 ore now buys
    # 1.25 magnet, so the ratio drops from 1 to 4/5.
    assert prod.input_rate("iron-ore") / prod.output_rate("magnet") == Fraction(4, 5)


def test_products_mode_gated_by_productivity_limitation(data: Dataset) -> None:
    """``conveyor-belt-2`` is outside the whitelist, so products mode is illegal.

    Ignoring this gate silently under-produces in game.
    """
    assert "conveyor-belt-2" not in data.limitation("productivity")
    modes = available_modes(data, data.recipe("conveyor-belt-2"), ProliferatorTier.MK3)
    assert ProliferatorMode.PRODUCTS not in modes
    assert ProliferatorMode.SPEED in modes


def test_speed_mode_is_always_legal(data: Dataset) -> None:
    for recipe_id in ("conveyor-belt-2", "magnet", "super-magnetic-ring"):
        modes = available_modes(data, data.recipe(recipe_id), ProliferatorTier.MK3)
        assert ProliferatorMode.SPEED in modes


def test_no_modes_offered_at_tier_none(data: Dataset) -> None:
    modes = available_modes(data, data.recipe("magnet"), ProliferatorTier.NONE)
    assert modes == (ProliferatorMode.NONE,)


def test_proliferator_consumption_is_inputs_over_sprays(data: Dataset) -> None:
    """One spray per input item; one proliferator unit supplies ``sprays`` of them."""
    # magnet consumes 1 iron-ore per craft; Mk.III supplies 60 sprays.
    a = adjust(
        data, data.recipe("magnet"), "arc-smelter", ProliferatorMode.SPEED, ProliferatorTier.MK3
    )
    assert a.proliferator_per_craft == Fraction(1, 60)
    assert a.proliferator_item_id == "proliferator-3"

    # super-magnetic-ring consumes 2 + 1 + 3 = 6 items per craft.
    b = adjust(
        data,
        data.recipe("super-magnetic-ring"),
        "assembling-machine-2",
        ProliferatorMode.PRODUCTS,
        ProliferatorTier.MK3,
    )
    assert b.proliferator_per_craft == Fraction(6, 60)


def test_unproliferated_recipe_consumes_no_proliferator(data: Dataset) -> None:
    a = adjust(data, data.recipe("magnet"), "arc-smelter")
    assert a.proliferator_per_craft == Fraction(0)
    assert a.proliferator_item_id is None


@pytest.mark.parametrize(
    ("tier", "sprays", "speed", "productivity"),
    [
        (ProliferatorTier.MK1, 12, Fraction(1, 4), Fraction(1, 8)),
        (ProliferatorTier.MK2, 24, Fraction(1, 2), Fraction(1, 5)),
        (ProliferatorTier.MK3, 60, Fraction(1), Fraction(1, 4)),
    ],
)
def test_module_table_matches_dataset(
    data: Dataset,
    tier: ProliferatorTier,
    sprays: int,
    speed: Fraction,
    productivity: Fraction,
) -> None:
    speed_mod = data.module(f"proliferator-{tier.value}-speed")
    prod_mod = data.module(f"proliferator-{tier.value}-products")
    assert speed_mod.sprays == sprays
    assert speed_mod.speed == speed
    assert prod_mod.productivity == productivity
    assert prod_mod.limitation == "productivity"
    assert speed_mod.limitation is None


# --- footprints ------------------------------------------------------------


def test_machine_footprint_area(data: Dataset) -> None:
    """Fewer machines can occupy more space, which is why area is the objective."""
    assert machine_footprint("arc-smelter") == 9
    assert machine_footprint("assembling-machine-2") == 16
    assert machine_footprint("chemical-plant") == 40


def test_every_lab_machine_resolves_to_a_footprint(data: Dataset) -> None:
    unresolved = [
        item.id for item in data.iter_items() if item.machine and machine_footprint(item.id) <= 0
    ]
    assert unresolved == []
