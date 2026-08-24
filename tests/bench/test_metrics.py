"""Metrics must be derived from the placement, never trusted from ``stats``.

A strategy reporting its own numbers is marking its own homework: the whole
point of the bake-off is that both strategies are measured the same way by code
neither of them owns.
"""

from __future__ import annotations

from fractions import Fraction

from flab2bp.bench.metrics import measure
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


def _belt(
    x: int, y: int, *, z: Fraction | int = 0, out: int | None = None
) -> PlacedBuilding:
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
