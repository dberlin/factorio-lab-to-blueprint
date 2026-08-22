"""Tests for the FactorioLab DSP dataset loader.

Every test here runs fully offline against the vendored copy of the dataset.
The one test that touches the network is marked ``network`` and deselected by
default.
"""

from __future__ import annotations

import json
import os
from fractions import Fraction
from pathlib import Path

import pytest

from flab2bp.lab.data import (
    DATA_URL,
    VENDORED_DIR,
    DatasetNotAvailable,
    load_dataset,
    load_hash_index,
    load_vendored,
)
from flab2bp.lab.schema import Dataset, Item, Recipe

# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return load_vendored()


def test_vendored_files_are_present() -> None:
    assert (VENDORED_DIR / "data.json").is_file()
    assert (VENDORED_DIR / "hash.json").is_file()


def test_load_vendored_reports_game_version(ds: Dataset) -> None:
    assert ds.version == {"DSP": "0.10.29.21950"}
    assert ds.flags == frozenset(
        {"beltStack", "inactiveDrain", "miningSpeed", "power", "proliferator"}
    )


def test_dataset_counts(ds: Dataset) -> None:
    assert len(ds.items) == 486
    assert len(ds.recipes) == 493
    assert len(ds.categories) == 4


def test_load_dataset_offline_falls_back_to_vendored() -> None:
    """With the network forbidden and no cache, we still get a dataset."""
    ds = load_dataset(allow_network=False, cache_dir=Path("/nonexistent-cache-dir"))
    assert len(ds.items) == 486


def test_load_dataset_honours_explicit_path(tmp_path: Path) -> None:
    src = json.loads((VENDORED_DIR / "data.json").read_text())
    src["items"] = src["items"][:3]
    target = tmp_path / "trimmed.json"
    target.write_text(json.dumps(src))

    ds = load_dataset(path=target, allow_network=False)
    assert len(ds.items) == 3


def test_load_dataset_prefers_disk_cache_over_vendored(tmp_path: Path) -> None:
    src = json.loads((VENDORED_DIR / "data.json").read_text())
    src["items"] = src["items"][:5]
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    from flab2bp.lab.data import cache_path_for

    cache_path_for(DATA_URL, cache_dir).write_text(json.dumps(src))

    ds = load_dataset(allow_network=False, cache_dir=cache_dir)
    assert len(ds.items) == 5


def test_missing_everything_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flab2bp.lab.data.VENDORED_DIR", tmp_path / "nope")
    with pytest.raises(DatasetNotAvailable):
        load_dataset(allow_network=False, cache_dir=tmp_path / "also-nope")


# --------------------------------------------------------------------------
# Parsing / schema
# --------------------------------------------------------------------------


def test_super_magnetic_ring_recipe(ds: Dataset) -> None:
    r = ds.recipe("super-magnetic-ring")
    assert r.time == Fraction(3)
    assert r.inputs == {
        "electromagnetic-turbine": Fraction(2),
        "energetic-graphite": Fraction(1),
        "magnet": Fraction(3),
    }
    assert r.outputs == {"super-magnetic-ring": Fraction(1)}
    assert r.producers == (
        "assembling-machine-1",
        "assembling-machine-2",
        "assembling-machine-3",
        "df-recomposing-assembler",
    )
    assert r.is_locked
    assert not r.is_mining
    assert not r.is_technology


def test_assembling_machine_2_speed(ds: Dataset) -> None:
    m = ds.machine("assembling-machine-2")
    assert m.speed == Fraction(1)
    assert m.usage == Fraction(540)
    assert m.drain == Fraction(18)
    assert m.modules == 1
    assert m.type == "electric"
    assert not m.total_recipe


def test_machine_consumption_is_a_map_not_a_scalar(ds: Dataset) -> None:
    """`ray-receiver-pro` is the only machine that consumes an item to run."""
    assert ds.machine("ray-receiver-pro").consumption == {"graviton-lens": Fraction(1, 10)}
    assert ds.machine("arc-smelter").consumption == {}


def test_belt_speeds(ds: Dataset) -> None:
    assert ds.belt_speed("conveyor-belt-1") == Fraction(6)
    assert ds.belt_speed("conveyor-belt-2") == Fraction(12)
    assert ds.belt_speed("conveyor-belt-3") == Fraction(30)


def test_fractional_quantities_are_exact(ds: Dataset) -> None:
    """JSON decimals must become exact rationals, not binary floats."""
    r = ds.recipe("gas-giant-deuterium")
    assert r.outputs["deuterium"] == Fraction(8, 25)  # 0.32 exactly
    assert ds.recipe("ocean").time == Fraction(6, 5)  # 1.2 exactly
    assert ds.recipe("magnet").time == Fraction(3, 2)


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    src = json.loads((VENDORED_DIR / "data.json").read_text())
    src["items"][0]["someFutureKey"] = {"nested": 1}
    src["recipes"][0]["anotherFutureKey"] = 7
    src["totallyNewSection"] = [1, 2, 3]
    target = tmp_path / "future.json"
    target.write_text(json.dumps(src))

    ds = load_dataset(path=target, allow_network=False)
    assert len(ds.items) == 486


def test_missing_optional_subobjects_are_none(ds: Dataset) -> None:
    plain = ds.item("super-magnetic-ring")
    assert plain.machine is None
    assert plain.belt is None
    assert plain.module is None
    assert plain.stack == 100

    # The six proliferator effect items are the only ones with no `row`.
    assert ds.item("proliferator-3-products").row is None


# --------------------------------------------------------------------------
# Accessors
# --------------------------------------------------------------------------


def test_item_and_recipe_lookup_raise_on_unknown(ds: Dataset) -> None:
    assert isinstance(ds.item("iron-ingot"), Item)
    assert isinstance(ds.recipe("iron-ingot"), Recipe)
    with pytest.raises(KeyError):
        ds.item("no-such-item")
    with pytest.raises(KeyError):
        ds.recipe("no-such-recipe")
    assert ds.get_item("no-such-item") is None
    assert ds.get_recipe("no-such-recipe") is None


def test_recipes_producing_is_unfiltered(ds: Dataset) -> None:
    assert {r.id for r in ds.recipes_producing("refined-oil")} == {
        "plasma-refining",
        "reforming-refine",
    }
    assert ds.recipes_producing("no-such-item") == []


def test_craftable_recipes_producing_drops_excluded(ds: Dataset) -> None:
    """`x-ray-cracking` also yields graphite but is excluded by default."""
    assert {r.id for r in ds.recipes_producing("energetic-graphite")} == {
        "energetic-graphite",
        "x-ray-cracking",
    }
    assert {r.id for r in ds.craftable_recipes_producing("energetic-graphite")} == {
        "energetic-graphite"
    }


def test_default_excluded_recipes(ds: Dataset) -> None:
    assert "x-ray-cracking" in ds.default_recipe_excluded
    assert "silicon-ore" in ds.default_recipe_excluded
    assert len(ds.default_recipe_excluded) == 14
    assert "iron-ingot" not in ds.default_recipe_excluded


def test_defaults_block(ds: Dataset) -> None:
    d = ds.defaults
    assert d.min_machine_rank == (
        "arc-smelter",
        "assembling-machine-1",
        "chemical-plant",
        "matrix-lab",
    )
    assert d.min_belt == "conveyor-belt-1"
    assert d.max_belt == "conveyor-belt-3"
    assert d.module_rank == ("proliferator-3-products",)
    assert d.fuel_rank == ("coal",)


# --------------------------------------------------------------------------
# Findings the rate solver depends on
# --------------------------------------------------------------------------


def test_exactly_seven_items_have_multiple_producers(ds: Dataset) -> None:
    """Only these need a real LP; everything else is a unique-producer DAG."""
    multi = ds.items_with_multiple_producers()
    assert set(multi) == {
        "accumulator",
        "deuterium",
        "hydrogen",
        "organic-crystal",
        "refined-oil",
        "space-warper",
        "sulfuric-acid",
    }
    assert set(multi["refined-oil"]) == {"plasma-refining", "reforming-refine"}
    assert set(multi["hydrogen"]) == {
        "plasma-refining",
        "mass-energy-storage",
        "gas-giant-hydrogen",
        "ice-giant-hydrogen",
    }


def test_proliferator_modules(ds: Dataset) -> None:
    """Both -products and -speed variants exist for all three tiers."""
    expected = {
        "proliferator-1-products": (Fraction(1, 8), None, 12, Fraction(3, 10)),
        "proliferator-2-products": (Fraction(1, 5), None, 24, Fraction(7, 10)),
        "proliferator-3-products": (Fraction(1, 4), None, 60, Fraction(3, 2)),
        "proliferator-1-speed": (None, Fraction(1, 4), 12, Fraction(3, 10)),
        "proliferator-2-speed": (None, Fraction(1, 2), 24, Fraction(7, 10)),
        "proliferator-3-speed": (None, Fraction(1), 60, Fraction(3, 2)),
    }
    assert set(ds.module_ids) == set(expected)
    for mid, (prod, speed, sprays, consumption) in expected.items():
        m = ds.module(mid)
        assert m.productivity == prod, mid
        assert m.speed == speed, mid
        assert m.sprays == sprays, mid
        assert m.consumption == consumption, mid

    # Only the productivity variants are limited to a recipe whitelist.
    assert ds.module("proliferator-3-products").limitation == "productivity"
    assert ds.module("proliferator-3-speed").limitation is None
    assert ds.module("proliferator-3-products").proliferator == "proliferator-3"


def test_productivity_limitation_whitelist(ds: Dataset) -> None:
    allowed = ds.limitation("productivity")
    assert len(allowed) == 464
    for rid in ("super-magnetic-ring", "iron-ingot", "magnet", "energetic-graphite"):
        assert rid in allowed


def test_mining_recipes_are_flagged(ds: Dataset) -> None:
    """The raw-input cut line: `mining` flag plus the two ray-receiver recipes."""
    mining = {r.id for r in ds.recipes if r.is_mining}
    assert len(mining) == 22
    for rid in ("iron-vein", "copper-vein", "coal-vein", "crude-oil-seep", "ocean"):
        assert rid in mining
    assert "iron-ingot" not in mining

    # Every mining recipe is free of material inputs, which is what makes it a
    # valid place to cut the graph and belt the product in instead.
    for r in ds.recipes:
        if r.is_mining:
            assert r.inputs == {}


def test_total_recipe_machines(ds: Dataset) -> None:
    assert ds.machine("mining-machine").total_recipe is True
    assert ds.machine("advanced-mining-machine").total_recipe is True
    assert ds.machine("arc-smelter").total_recipe is False


# --------------------------------------------------------------------------
# Hash index
# --------------------------------------------------------------------------


def test_hash_index(ds: Dataset) -> None:
    h = load_hash_index(allow_network=False, cache_dir=Path("/nonexistent-cache-dir"))
    assert len(h.items) == 496
    assert len(h.recipes) == 495
    assert len(h.machines) == 52
    assert len(h.modules) == 10
    assert h.belts[:3] == ("conveyor-belt-1", "conveyor-belt-2", "conveyor-belt-3")
    assert h.items[2] is None  # holes are preserved so indices stay stable
    assert h.modules[4] == "proliferator-1-products"


# --------------------------------------------------------------------------
# Network (deselected by default)
# --------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.skipif(
    not os.environ.get("FLAB2BP_NETWORK_TESTS"),
    reason="set FLAB2BP_NETWORK_TESTS=1 to exercise the live dataset fetch",
)
def test_live_dataset_matches_vendored_shape() -> None:
    ds = load_dataset(allow_network=True, force_refresh=True)
    assert len(ds.items) > 400
    assert ds.recipe("iron-ingot").time == Fraction(1)
