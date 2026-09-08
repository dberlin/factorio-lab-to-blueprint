"""Metrics must be derived from the placement, never trusted from ``stats``.

A strategy reporting its own numbers is marking its own homework: the whole
point of the bake-off is that both strategies are measured the same way by code
neither of them owns.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.bench.metrics import measure
from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding, Placement

#: Deliberately a round number rather than the real assembler footprint. These
#: tests exercise ``measure()``'s arithmetic, so the geometry is a fixture, not a
#: claim about DSP -- and pinning it here keeps them stable when the catalog's
#: derived footprints change (as they did when assemblers went 4x4 -> 3x3).
_TEST_MACHINE_SIZE = 4


def _assembler(x: int, y: int, *, recipe: int = 1) -> PlacedBuilding:
    return PlacedBuilding(
        item_id=2304,
        model_index=66,
        x=x,
        y=y,
        width=_TEST_MACHINE_SIZE,
        height=_TEST_MACHINE_SIZE,
        recipe_id=recipe,
    )


def _belt(x: int, y: int, *, z: Fraction | int = 0, out: int | None = None) -> PlacedBuilding:
    return PlacedBuilding(item_id=2002, model_index=36, x=x, y=y, z=Fraction(z), output_obj=out)


def _sorter(x: int, y: int, *, inp: int | None, out: int | None) -> PlacedBuilding:
    return PlacedBuilding(
        item_id=2013,
        model_index=43,
        x=x,
        y=y,
        x2=x,
        y2=y + 1,
        z2=Fraction(0),
        input_obj=inp,
        output_obj=out,
    )


def _substation(x: int, y: int) -> PlacedBuilding:
    return PlacedBuilding(item_id=2212, model_index=68, x=x, y=y, width=5, height=5)


def _tower(x: int, y: int) -> PlacedBuilding:
    return PlacedBuilding(
        item_id=catalog.TESLA_TOWER_ID,
        model_index=catalog.building(catalog.TESLA_TOWER_ID).model_index,
        x=x,
        y=y,
    )


def _coater(x: int, y: int) -> PlacedBuilding:
    return PlacedBuilding(
        item_id=catalog.SPRAY_COATER_ID,
        model_index=catalog.building(catalog.SPRAY_COATER_ID).model_index,
        x=x,
        y=y,
    )


def test_measures_geometry_from_buildings_not_stats() -> None:
    # stats claims an absurd area; the harness must ignore it.
    placement = Placement(
        buildings=(_assembler(0, 0), _assembler(6, 0)),
        stats={"area": 1.0, "machines": 999.0},
    )
    m = measure(placement)
    assert m.machines == 2
    # x spans 0..9 inclusive, y spans 0..3 inclusive
    assert m.width == 10
    assert m.height == 4
    assert m.area == 40
    assert m.used_tiles == 32


def test_packing_efficiency_exposes_a_thin_ribbon() -> None:
    """A strategy winning bounding box by being long and thin must be visible."""
    dense = Placement(buildings=(_assembler(0, 0), _assembler(4, 0)))
    sparse = Placement(buildings=(_assembler(0, 0), _assembler(40, 0)))
    assert measure(dense).packing_efficiency > measure(sparse).packing_efficiency


def test_counts_composition_by_kind() -> None:
    placement = Placement(
        buildings=(
            _assembler(0, 0),
            _belt(0, 5),
            _belt(1, 5),
            _sorter(0, 4, inp=0, out=1),
        )
    )
    m = measure(placement)
    assert m.machines == 1
    assert m.belt_tiles == 2
    assert m.sorters == 1


def test_direct_inserts_are_sorters_with_both_ends_on_machines() -> None:
    placement = Placement(
        buildings=(
            _assembler(0, 0),
            _assembler(5, 0),
            _belt(0, 5),
            # machine -> machine: a direct insert
            _sorter(4, 0, inp=0, out=1),
            # machine -> belt: not a direct insert
            _sorter(0, 4, inp=0, out=2),
        )
    )
    assert measure(placement).direct_inserts == 1


def test_altitude_levels_reports_stacking_depth() -> None:
    flat = Placement(buildings=(_belt(0, 0), _belt(1, 0)))
    stacked = Placement(buildings=(_belt(0, 0), _belt(0, 0, z=1), _belt(0, 0, z=2)))
    assert measure(flat).altitude_levels == 1
    assert measure(stacked).altitude_levels == 3


def test_empty_placement_does_not_divide_by_zero() -> None:
    m = measure(Placement(buildings=()))
    assert m.machines == 0
    assert m.packing_efficiency == 0.0


def test_measure_counts_a_substation_as_a_tower() -> None:
    buildings = [_substation(0, 0)]
    assert measure(Placement(buildings=buildings)).towers == 1


def test_measure_excludes_a_substation_from_the_machine_count() -> None:
    buildings = [_substation(0, 0)]
    assert measure(Placement(buildings=buildings)).machines == 0


@pytest.mark.parametrize("item_id", [catalog.RAY_RECEIVER_ID, catalog.ENERGY_EXCHANGER_ID])
def test_power_producers_remain_machines_and_direct_insert_endpoints(item_id: int) -> None:
    info = catalog.building(item_id)
    producer = PlacedBuilding(
        item_id=item_id,
        model_index=info.model_index,
        x=10,
        y=0,
        width=info.width,
        height=info.height,
    )
    placement = Placement(
        buildings=(
            _assembler(0, 0),
            producer,
            _substation(20, 0),
            PlacedBuilding(item_id=2201, model_index=44, x=30, y=0),
            PlacedBuilding(item_id=2202, model_index=71, x=35, y=0),
            _sorter(5, 0, inp=0, out=1),
            _sorter(5, 1, inp=1, out=0),
            # A supply tower is not a production endpoint, even if linked.
            _sorter(15, 0, inp=1, out=2),
        )
    )

    metrics = measure(placement)
    assert metrics.machines == 2
    assert metrics.direct_inserts == 2
    # Categories overlap: the producer is also a member of the power network.
    assert metrics.towers == 4


def test_machine_metrics_include_piler_but_exclude_tower_and_coater() -> None:
    piler = catalog.building(catalog.PILER_ID)
    placement = Placement(
        buildings=(
            _assembler(0, 0),
            _assembler(10, 0),
            _tower(20, 0),
            _coater(21, 0),
            PlacedBuilding(
                item_id=catalog.PILER_ID,
                model_index=piler.model_index,
                x=25,
                y=0,
            ),
            _sorter(4, 0, inp=0, out=4),
            _sorter(15, 0, inp=4, out=1),
            _sorter(20, 0, inp=0, out=2),
            _sorter(21, 0, inp=3, out=1),
        )
    )
    measured = measure(placement)
    assert measured.machines == 3
    assert measured.direct_inserts == 2
    assert measured.towers == 1
