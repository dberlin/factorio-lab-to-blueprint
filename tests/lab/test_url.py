"""Tests for parsing a FactorioLab URL into a typed :class:`LabRequest`."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.lab import params as P
from flab2bp.lab.url import (
    DisplayRate,
    LabRequest,
    ObjectiveType,
    ObjectiveUnit,
    Preset,
    UnsupportedDatasetError,
    UnsupportedZipVersionError,
    parse_url,
)

EXAMPLE = (
    "https://factoriolab.github.io/dsp/flow"
    "?o=super-magnetic-ring*60"
    "&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
    "&mps=proliferator-2-products"
    "&v=11"
)


class TestExampleUrl:
    @pytest.fixture
    def req(self) -> LabRequest:
        return parse_url(EXAMPLE)

    def test_mod_id(self, req: LabRequest) -> None:
        assert req.mod_id == "dsp"

    def test_is_bare(self, req: LabRequest) -> None:
        assert req.is_bare is True
        assert req.zip_version == "11"

    def test_single_output_objective(self, req: LabRequest) -> None:
        assert len(req.objectives) == 1
        obj = req.objectives[0]
        assert obj.target_id == "super-magnetic-ring"
        assert obj.value == Fraction(60)
        assert obj.unit is ObjectiveUnit.Items
        assert obj.type is ObjectiveType.Output
        assert obj.is_recipe_objective is False

    def test_objective_optional_fields_absent(self, req: LabRequest) -> None:
        obj = req.objectives[0]
        assert obj.machine_id is None
        assert obj.modules is None
        assert obj.beacons is None
        assert obj.overclock is None
        assert obj.fuel_id is None

    def test_belt(self, req: LabRequest) -> None:
        assert req.belt_id == "conveyor-belt-2"

    def test_machine_rank(self, req: LabRequest) -> None:
        assert req.machine_rank_ids == [
            "arc-smelter",
            "assembling-machine-2",
            "chemical-plant",
            "matrix-lab",
        ]

    def test_proliferator_spray(self, req: LabRequest) -> None:
        assert req.proliferator_spray_id == "proliferator-2-products"

    def test_display_rate_defaults_to_per_minute(self, req: LabRequest) -> None:
        """`odr` is absent, and FactorioLab's initial state is PerMinute."""
        assert req.display_rate is DisplayRate.PerMinute

    def test_unset_settings_are_none(self, req: LabRequest) -> None:
        assert req.preset is None
        assert req.module_rank_ids is None
        assert req.excluded_recipe_ids is None
        assert req.mining_bonus is None
        assert req.items == {}
        assert req.recipes == {}
        assert req.machines == {}
        assert req.modules == ()
        assert req.beacons == ()


class TestObjectiveFields:
    """Field order: targetId*value*unit*type*machineId*modules*beacons*overclock*fuelId"""

    def test_full_field_order(self) -> None:
        req = parse_url(
            "https://factoriolab.github.io/dsp/list"
            "?e=1*proliferator-3-products"
            "&b=2*0*none*4"
            "&o=iron-ingot*30*0*0*arc-smelter*0*0*150*coal"
            "&v=11"
        )
        obj = req.objectives[0]
        assert obj.target_id == "iron-ingot"
        assert obj.value == Fraction(30)
        assert obj.unit is ObjectiveUnit.Items
        assert obj.type is ObjectiveType.Output
        assert obj.machine_id == "arc-smelter"
        assert obj.modules is not None and len(obj.modules) == 1
        assert obj.modules[0].id == "proliferator-3-products"
        assert obj.beacons is not None and len(obj.beacons) == 1
        assert obj.overclock == Fraction(150)
        assert obj.fuel_id == "coal"

    def test_defaults_when_trailing_fields_stripped(self) -> None:
        req = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot&v=11")
        obj = req.objectives[0]
        assert obj.value == Fraction(1)
        assert obj.unit is ObjectiveUnit.Items
        assert obj.type is ObjectiveType.Output

    def test_machines_unit_means_target_is_a_recipe(self) -> None:
        req = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*5*3&v=11")
        obj = req.objectives[0]
        assert obj.unit is ObjectiveUnit.Machines
        assert obj.is_recipe_objective is True

    def test_objective_types(self) -> None:
        req = parse_url(
            "https://factoriolab.github.io/dsp/list"
            "?o=iron-ingot*5*0*1&o=copper-ingot*5*0*2&o=magnet*5*0*3&v=11"
        )
        assert [o.type for o in req.objectives] == [
            ObjectiveType.Input,
            ObjectiveType.Maximize,
            ObjectiveType.Limit,
        ]

    def test_multiple_objectives_get_sequential_ids(self) -> None:
        req = parse_url(
            "https://factoriolab.github.io/dsp/list?o=iron-ingot*1&o=copper-ingot*2&v=11"
        )
        assert [o.id for o in req.objectives] == ["1", "2"]

    def test_exact_rational_value(self) -> None:
        req = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*1/3&v=11")
        assert req.objectives[0].value == Fraction(1, 3)


class TestSettingArrays:
    def test_item_settings(self) -> None:
        # i = itemId*beltId*wagonId*stack*excludeRockets
        req = parse_url(
            "https://factoriolab.github.io/dsp/list?o=iron-ingot*1&i=iron-ore*conveyor-belt-3**4*1&v=11"
        )
        item = req.items["iron-ore"]
        assert item.belt_id == "conveyor-belt-3"
        assert item.wagon_id is None
        assert item.stack == Fraction(4)
        assert item.exclude_rockets is True

    def test_recipe_settings(self) -> None:
        # r = recipeId*machineId*modules*beacons*overclock*cost*fuelId*productivity
        req = parse_url(
            "https://factoriolab.github.io/dsp/list"
            "?o=iron-ingot*1&e=1*proliferator-3-products"
            "&r=magnet*arc-smelter*0**100*5*coal*25"
            "&v=11"
        )
        rec = req.recipes["magnet"]
        assert rec.machine_id == "arc-smelter"
        assert rec.modules is not None and rec.modules[0].id == "proliferator-3-products"
        assert rec.overclock == Fraction(100)
        assert rec.cost == Fraction(5)
        assert rec.fuel_id == "coal"
        assert rec.productivity == Fraction(25)

    def test_machine_settings(self) -> None:
        # m = machineId*modules*beacons*fuelId*overclock
        req = parse_url(
            "https://factoriolab.github.io/dsp/list"
            "?o=iron-ingot*1&e=2*proliferator-1-products"
            "&m=assembling-machine-3*0**coal*120"
            "&v=11"
        )
        mach = req.machines["assembling-machine-3"]
        assert mach.modules is not None and mach.modules[0].count == Fraction(2)
        assert mach.fuel_id == "coal"
        assert mach.overclock == Fraction(120)

    def test_module_and_beacon_lists(self) -> None:
        # e = count*moduleId ; b = count*modules*beaconId*total
        req = parse_url(
            "https://factoriolab.github.io/dsp/list"
            "?o=iron-ingot*1&e=4*proliferator-2-products&b=8*0*none*16&v=11"
        )
        assert req.modules[0].count == Fraction(4)
        assert req.modules[0].id == "proliferator-2-products"
        assert req.beacons[0].count == Fraction(8)
        assert req.beacons[0].id == "none"
        assert req.beacons[0].total == Fraction(16)

    def test_single_repeated_key_is_coerced_to_list(self) -> None:
        """`Migration.migrate` coerces o/i/r/m/e/b from string to array."""
        req = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*1&v=11")
        assert isinstance(req.objectives, tuple)
        assert len(req.objectives) == 1


class TestScalarSettings:
    def test_numeric_and_boolean_settings(self) -> None:
        req = parse_url(
            "https://factoriolab.github.io/dsp/list"
            "?o=iron-ingot*1&odr=0&mpr=2&rnp=1&orm=0&moc=150&bmi=30&bre=10&brp=5&v=11"
        )
        assert req.display_rate is DisplayRate.PerSecond
        assert req.preset is Preset.Beacon8
        assert req.net_production_only is True
        assert req.require_machines_output is False
        assert req.overclock == Fraction(150)
        assert req.mining_bonus == Fraction(30)
        assert req.research_bonus == Fraction(10)
        assert req.research_productivity == Fraction(5)

    def test_rank_lists(self) -> None:
        req = parse_url(
            "https://factoriolab.github.io/dsp/list"
            "?o=iron-ingot*1&mfr=coal~deuterium&mer=proliferator-3-products&v=11"
        )
        assert req.fuel_rank_ids == ["coal", "deuterium"]
        assert req.module_rank_ids == ["proliferator-3-products"]

    def test_cost_settings(self) -> None:
        req = parse_url(
            "https://factoriolab.github.io/dsp/list?o=iron-ingot*1&cma=2&cun=1000000&v=11"
        )
        assert req.costs.machine == Fraction(2)
        assert req.costs.unproduceable == Fraction(1000000)
        assert req.costs.factor is None


class TestSubsetSettings:
    """`iex`/`rex`/`tre` are range-encoded indices into hash.json -- even when bare."""

    def test_excluded_recipes_resolve_against_mod_hash(self) -> None:
        mh = P.load_mod_hash("dsp")
        idx = mh.recipes.index("magnet")
        req = parse_url(
            f"https://factoriolab.github.io/dsp/list?o=iron-ingot*1&rex={P.n_to_id(idx)}&v=11"
        )
        assert req.excluded_recipe_ids == {"magnet"}

    def test_excluded_items_range(self) -> None:
        mh = P.load_mod_hash("dsp")
        start = mh.items.index("iron-ore")
        ids = [i for i in mh.items[start : start + 3] if i is not None]
        value = f"{P.n_to_id(start)}~{P.n_to_id(start + 2)}"
        req = parse_url(f"https://factoriolab.github.io/dsp/list?o=iron-ingot*1&iex={value}&v=11")
        assert req.excluded_item_ids == set(ids)

    def test_empty_marker_gives_empty_set(self) -> None:
        req = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*1&rex=_&v=11")
        assert req.excluded_recipe_ids == set()


class TestCompressedUrls:
    def test_compressed_url_matches_equivalent_bare_url(self) -> None:
        """The two encodings of the same settings must parse identically."""
        mh = P.load_mod_hash("dsp")
        bare = parse_url(EXAMPLE)
        assert bare.machine_rank_ids is not None
        ranks = "~".join(P.n_to_id(mh.machines.index(m)) for m in bare.machine_rank_ids)
        inner = (
            f"o={P.n_to_id(mh.items.index('super-magnetic-ring'))}*60"
            f"&ibe={P.n_to_id(mh.belts.index('conveyor-belt-2'))}"
            f"&mmr={ranks}"
            f"&mps={P.n_to_id(mh.modules.index('proliferator-2-products'))}"
            "&v=11"
        )
        url = f"https://factoriolab.github.io/dsp/flow?z={P.deflate(inner)}&v=11"
        zipped = parse_url(url)

        assert zipped.is_bare is False
        assert bare.is_bare is True
        assert zipped.objectives[0].target_id == bare.objectives[0].target_id
        assert zipped.objectives[0].value == bare.objectives[0].value
        assert zipped.belt_id == bare.belt_id
        assert zipped.machine_rank_ids == bare.machine_rank_ids
        assert zipped.proliferator_spray_id == bare.proliferator_spray_id

    def test_bare_ids_inside_a_zip_payload_do_not_resolve(self) -> None:
        """Guards the bare/hash split: `z` means ids are indices, always."""
        inner = "o=super-magnetic-ring*60&ibe=conveyor-belt-2&v=11"
        url = f"https://factoriolab.github.io/dsp/flow?z={P.deflate(inner)}&v=11"
        req = parse_url(url)
        assert req.objectives[0].target_id == ""
        assert req.belt_id is None

    def test_hash_encoded_ids_are_resolved(self) -> None:
        """Inside `z=`, ids are base-64 indices into hash.json."""
        mh = P.load_mod_hash("dsp")
        item = P.n_to_id(mh.items.index("super-magnetic-ring"))
        belt = P.n_to_id(mh.belts.index("conveyor-belt-2"))
        machines = "~".join(
            P.n_to_id(mh.machines.index(m)) for m in ("arc-smelter", "assembling-machine-2")
        )
        inner = f"o={item}*60&ibe={belt}&mmr={machines}&v=11"
        url = f"https://factoriolab.github.io/dsp/flow?z={P.deflate(inner)}&v=11"
        req = parse_url(url)
        assert req.objectives[0].target_id == "super-magnetic-ring"
        assert req.belt_id == "conveyor-belt-2"
        assert req.machine_rank_ids == ["arc-smelter", "assembling-machine-2"]

    def test_hash_recipe_objective_resolves_against_recipes(self) -> None:
        mh = P.load_mod_hash("dsp")
        recipe = P.n_to_id(mh.recipes.index("magnet"))
        inner = f"o={recipe}*4*3&v=11"
        url = f"https://factoriolab.github.io/dsp/flow?z={P.deflate(inner)}&v=11"
        obj = parse_url(url).objectives[0]
        assert obj.is_recipe_objective is True
        assert obj.target_id == "magnet"

    def test_truncated_payload_is_mended(self) -> None:
        """A link previewer that eats the trailing pad must not break the URL."""
        for i in range(1, 2000):
            inner = f"o=super-magnetic-ring*{i}&ibe=conveyor-belt-2&v=11"
            payload = P.deflate(inner)
            if payload.endswith(P.ZEMPTY):
                break
        else:  # pragma: no cover - sample range always contains a padded payload
            pytest.fail("no padded payload found")
        url = f"https://factoriolab.github.io/dsp/flow?z={payload[:-1]}&v=11"
        assert parse_url(url).objectives[0].value == Fraction(i)

    def test_legacy_query_unsafe_payload(self) -> None:
        inner = "o=iron-ingot*10&v=11"
        payload = P.deflate(inner).replace("-", "+").replace(".", "/").replace("_", "=")
        url = f"https://factoriolab.github.io/dsp/flow?z={payload}&v=11"
        assert parse_url(url).objectives[0].value == Fraction(10)


class TestPercentDecoding:
    def test_bare_params_are_percent_decoded(self) -> None:
        """`Migration.migrate` decodeURIComponent's bare params."""
        req = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot%2A5&v=11")
        assert req.objectives[0].value == Fraction(5)


class TestErrors:
    @pytest.mark.parametrize("version", ["0", "4", "8", "10"])
    def test_pre_v11_rejected(self, version: str) -> None:
        url = f"https://factoriolab.github.io/dsp/list?o=iron-ingot*1&v={version}"
        with pytest.raises(UnsupportedZipVersionError) as exc:
            parse_url(url)
        assert version in str(exc.value)

    def test_missing_version_on_zipped_url_is_v0_and_rejected(self) -> None:
        """A payload with no `v` coalesces to Version0 in `Migration.migrate`."""
        url = f"https://factoriolab.github.io/dsp/list?z={P.deflate('o=iron-ingot*1')}"
        with pytest.raises(UnsupportedZipVersionError) as exc:
            parse_url(url)
        assert "'0'" in str(exc.value)

    def test_future_version_rejected(self) -> None:
        url = "https://factoriolab.github.io/dsp/list?o=iron-ingot*1&v=12"
        with pytest.raises(UnsupportedZipVersionError):
            parse_url(url)

    def test_non_dsp_dataset_rejected(self) -> None:
        url = "https://factoriolab.github.io/factorio/list?o=iron-plate*1&v=11"
        with pytest.raises(UnsupportedDatasetError) as exc:
            parse_url(url)
        assert "dsp" in str(exc.value)

    def test_missing_dataset_segment_rejected(self) -> None:
        with pytest.raises(UnsupportedDatasetError):
            parse_url("https://factoriolab.github.io/?o=iron-ingot*1&v=11")

    def test_no_objectives_rejected(self) -> None:
        with pytest.raises(ValueError, match="objective"):
            parse_url("https://factoriolab.github.io/dsp/list?ibe=conveyor-belt-2&v=11")

    def test_corrupt_zip_payload_reports_clearly(self) -> None:
        with pytest.raises(P.LabUrlError):
            parse_url("https://factoriolab.github.io/dsp/list?z=zzzz&v=11")


class TestImmutability:
    def test_request_is_frozen(self) -> None:
        req = parse_url(EXAMPLE)
        with pytest.raises(AttributeError):
            req.belt_id = "conveyor-belt-3"  # type: ignore[misc]

    def test_objective_is_frozen(self) -> None:
        obj = parse_url(EXAMPLE).objectives[0]
        with pytest.raises(AttributeError):
            obj.value = Fraction(1)  # type: ignore[misc]
