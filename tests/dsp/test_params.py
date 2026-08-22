"""Parameter blocks for machines configured by a MODE rather than a recipe.

The Energy Exchanger assertions are ground truth: they compare against the
parameter tuples that real, working blueprints in ``tests/fixtures`` actually
contain, not against a restatement of the implementation.  The corpus holds 45
exchangers carrying both poles -- and one fixture holds twelve of each -- so the
tri-state is pinned by data rather than inferred from the decompiled clamp.

The Ray Receiver has no such backing: it appears zero times in the corpus.  Its
encoding comes from the game's own dispatch table alone, and the tests below say
so explicitly rather than implying a confidence the evidence does not support.
"""

from __future__ import annotations

import glob
from collections import Counter

import pytest

from flab2bp.dsp import catalog, codec, params

ENERGY_EXCHANGER_ID = 2209
RAY_RECEIVER_ID = 2208
CRITICAL_PHOTON_ITEM_ID = 1208


def observed_parameters(item_id: int) -> Counter[tuple[int, ...]]:
    """Every parameter tuple real blueprints carry for ``item_id``."""
    seen: Counter[tuple[int, ...]] = Counter()
    for path in sorted(glob.glob("tests/fixtures/*.txt")):
        with open(path) as fh:
            text = fh.read().strip()
        try:
            blueprint = codec.decode(text)
        except Exception:  # noqa: BLE001 - the DYBP fixture is a negative control
            continue
        for building in blueprint.buildings:
            if building.item_id == item_id:
                seen[tuple(building.parameters)] += 1
    return seen


# --- Energy Exchanger: pinned by real blueprints ---------------------------


class TestEnergyExchangerAgainstRealBlueprints:
    def test_the_corpus_carries_both_poles(self) -> None:
        """Without both, the tri-state would be inferred rather than observed."""
        seen = observed_parameters(ENERGY_EXCHANGER_ID)
        assert seen, "no Energy Exchangers in the corpus; this suite proves nothing"
        assert set(seen) == {(1,), (-1,)}, (
            f"expected only charge and discharge blocks, saw {sorted(seen)}. A new "
            "value means the encoding below is incomplete."
        )

    def test_charge_matches_the_observed_block(self) -> None:
        assert params.energy_exchanger(params.ExchangerMode.CHARGE) == (1,)
        assert (1,) in observed_parameters(ENERGY_EXCHANGER_ID)

    def test_discharge_matches_the_observed_block(self) -> None:
        assert params.energy_exchanger(params.ExchangerMode.DISCHARGE) == (-1,)
        assert (-1,) in observed_parameters(ENERGY_EXCHANGER_ID)

    def test_standby_is_expressible_though_no_blueprint_uses_it(self) -> None:
        """Nobody blueprints an idle exchanger, but the game clamps to -1..1."""
        assert params.energy_exchanger(params.ExchangerMode.STANDBY) == (0,)
        assert (0,) not in observed_parameters(ENERGY_EXCHANGER_ID)

    def test_charge_and_discharge_are_opposite_poles(self) -> None:
        charge = params.energy_exchanger(params.ExchangerMode.CHARGE)
        discharge = params.energy_exchanger(params.ExchangerMode.DISCHARGE)
        assert charge[0] == -discharge[0]

    def test_every_block_is_one_word(self) -> None:
        """The Exchanger row of ToParamsArray fixes the width at one."""
        for mode in params.ExchangerMode:
            assert len(params.energy_exchanger(mode)) == 1
        assert all(len(p) == 1 for p in observed_parameters(ENERGY_EXCHANGER_ID))


# --- Ray Receiver: no corpus backing, and the tests say so -----------------


class TestRayReceiverHasNoCorpusEvidence:
    def test_the_corpus_contains_none(self) -> None:
        """Guards the claim in the module docstring.

        If a Ray Receiver ever appears in a fixture, this fails and the encoding
        below should be checked against it rather than trusted.
        """
        assert observed_parameters(RAY_RECEIVER_ID) == Counter()

    def test_photon_mode_names_the_critical_photon_item(self) -> None:
        assert params.ray_receiver(params.GammaMode.PHOTON) == (CRITICAL_PHOTON_ITEM_ID,)

    def test_power_mode_produces_no_item(self) -> None:
        assert params.ray_receiver(params.GammaMode.POWER) == (0,)


# --- the registry ----------------------------------------------------------


class TestModeDrivenRegistry:
    def test_every_mode_driven_recipe_yields_a_block(self) -> None:
        for recipe in catalog.NO_DSP_RECIPE:
            entry = catalog.MODE_DRIVEN_MACHINE[recipe]
            block = params.parameters_for(recipe)
            assert isinstance(block, tuple)
            assert block, f"{recipe} produced an empty parameter block"
            assert entry.machine_item_id in (ENERGY_EXCHANGER_ID, RAY_RECEIVER_ID)

    def test_the_two_exchanger_recipes_take_opposite_poles(self) -> None:
        """accumulator-full charges; accumulator-discharge does the reverse."""
        assert params.parameters_for("accumulator-full") == (1,)
        assert params.parameters_for("accumulator-discharge") == (-1,)

    def test_both_photon_recipes_share_one_block(self) -> None:
        """The graviton lens is an item fed in, not a different machine mode.

        FactorioLab splits these into two recipes because the lens doubles the
        yield (6/s versus 12/s), but the building is the same Ray Receiver set to
        the same product. Emitting different parameter blocks would be wrong.
        """
        assert params.parameters_for("critical-photon") == params.parameters_for(
            "critical-photon-graviton"
        )

    def test_registry_covers_exactly_the_no_recipe_set(self) -> None:
        assert set(catalog.MODE_DRIVEN_MACHINE) == set(catalog.NO_DSP_RECIPE)


# --- refusing to guess -----------------------------------------------------


class TestUnknownModesRaise:
    def test_an_unregistered_recipe_raises(self) -> None:
        with pytest.raises(KeyError, match="not a mode-driven"):
            params.parameters_for("iron-ingot")

    def test_a_non_mode_argument_raises(self) -> None:
        with pytest.raises(TypeError):
            params.energy_exchanger("charge")  # type: ignore[arg-type]

    def test_a_non_mode_argument_raises_for_gamma(self) -> None:
        with pytest.raises(TypeError):
            params.ray_receiver("photon")  # type: ignore[arg-type]
