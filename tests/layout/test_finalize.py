"""Strategy-independent exact cleanup of emitted placements."""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog, codec
from flab2bp.layout import finalize
from flab2bp.layout.base import PlacedBuilding, Placement
from tests.layout.test_freeform import two_stage_spec


def _belt(x: int, y: int, *, output: int | None) -> PlacedBuilding:
    item_id = min(catalog.BELT_IDS)
    return PlacedBuilding(
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=x,
        y=y,
        z=Fraction(),
        output_obj=output,
    )


def _building(
    item_id: int,
    x: int,
    y: int,
    *,
    z: Fraction = Fraction(),
    yaw: float = 0.0,
) -> PlacedBuilding:
    info = catalog.building(item_id)
    return PlacedBuilding(
        item_id=item_id,
        model_index=info.model_index,
        x=x,
        y=y,
        z=z,
        width=info.width,
        height=info.height,
        yaw=yaw,
    )


def _extent(width: int, height: int) -> tuple[PlacedBuilding, PlacedBuilding]:
    return (
        _belt(0, 0, output=None),
        _belt(width - 1, height - 1, output=None),
    )


@dataclass(frozen=True)
class _Report:
    errors: tuple[object, ...] = ()


def test_remove_buildings_bypasses_removed_chain_and_reindexes() -> None:
    placement = Placement(
        buildings=(
            _belt(0, 0, output=1),
            _belt(1, 0, output=2),
            _belt(2, 0, output=None),
        )
    )

    changed = finalize._remove_buildings(placement, frozenset({1}))

    assert [(belt.x, belt.output_obj) for belt in changed.buildings] == [
        (0, 1),
        (2, None),
    ]


def test_compaction_prunes_open_belt_leaves_to_a_structural_fixed_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placement = Placement(
        buildings=(
            _belt(0, 1, output=1),
            _belt(1, 1, output=2),
            _belt(2, 1, output=None),
            _belt(1, 0, output=1),
        )
    )
    calls: list[Placement] = []

    def certify(candidate: Placement, *_args: object, **_kwargs: object) -> _Report:
        calls.append(candidate)
        return _Report()

    monkeypatch.setattr(finalize, "_certify", certify)
    compacted = finalize.compact_open_boundary_belts(
        placement,
        two_stage_spec(),
        expect_power=False,
    )

    assert len(calls) == 1
    assert compacted.area == 1
    assert [(belt.x, belt.y) for belt in compacted.buildings] == [(1, 1)]


def test_compaction_preserves_original_when_certification_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placement = Placement(
        buildings=(
            _belt(0, 0, output=1),
            _belt(1, 0, output=None),
        )
    )

    def reject(*_args: object, **_kwargs: object) -> _Report:
        return _Report(errors=(object(),))

    monkeypatch.setattr(finalize, "_certify", reject)

    assert (
        finalize.compact_open_boundary_belts(
            placement,
            two_stage_spec(),
            expect_power=False,
        )
        is placement
    )


@pytest.mark.parametrize(("width", "height"), ((43, 35), (35, 43)))
def test_finalization_selects_the_smallest_band_for_broke2_extent(
    width: int,
    height: int,
) -> None:
    placement = Placement(buildings=_extent(width, height))

    finalized = finalize.finalize_placement(placement)

    assert finalized.stats["area_segments"] == 160.0
    assert finalized.stats["band_rotated"] == 0.0


def test_finalization_physically_rotates_an_extent_that_only_fits_turned() -> None:
    placement = Placement(buildings=_extent(10, 161))

    finalized = finalize.finalize_placement(placement)
    area = codec.placement_to_blueprint(finalized).areas[0]

    assert finalized.bounds == (0, 0, 160, 9)
    assert finalized.stats["area_segments"] == 40.0
    assert finalized.stats["band_rotated"] == 1.0
    assert (area.width, area.height, area.area_segments) == (161, 10, 40)


def test_broke2_tower_pair_uses_the_safe_smallest_band_orientation() -> None:
    placement = Placement(
        buildings=(
            *_extent(43, 35),
            _building(catalog.TESLA_TOWER_ID, 22, 10),
            _building(catalog.TESLA_TOWER_ID, 20, 8),
        )
    )

    finalized = finalize.finalize_placement(placement)

    assert finalized.stats["area_segments"] == 160.0
    assert finalized.stats["band_rotated"] == 1.0
    assert finalized.bounds == (0, 0, 34, 42)


def test_broke2_splitter_region_is_rejected_by_projected_addon_keepout() -> None:
    # Original blueprint records: host belt #100, supply belt #478,
    # Spray Coater #479, and Splitter #794.
    placement = Placement(
        buildings=(
            *_extent(43, 35),
            _building(min(catalog.BELT_IDS), 26, 15),
            _building(min(catalog.BELT_IDS), 25, 15, z=Fraction(1)),
            PlacedBuilding(
                item_id=catalog.SPRAY_COATER_ID,
                model_index=catalog.building(catalog.SPRAY_COATER_ID).model_index,
                x=26,
                y=15,
                yaw=90.0,
            ),
            _building(catalog.SPLITTER_ID, 25, 17, z=Fraction(1)),
        )
    )

    with pytest.raises(finalize.ProjectionRefusal) as exc:
        finalize.finalize_placement(placement)

    assert exc.value.checks == ("game.addon_splitter_clearance",)
    assert "(4, 5)" in str(exc.value)


def test_finalization_rejects_a_band_where_a_sorter_compresses_too_close() -> None:
    belt_id = min(catalog.BELT_IDS)
    sorter_id = catalog.item_id("sorter-1")
    placement = Placement(
        buildings=(
            _building(belt_id, 0, 0),
            _building(belt_id, 1, 0),
            _building(belt_id, 19, 4),
            PlacedBuilding(
                item_id=sorter_id,
                model_index=catalog.building(sorter_id).model_index,
                x=0,
                y=0,
                x2=1,
                y2=0,
                z2=Fraction(),
                yaw=90.0,
                yaw2=90.0,
                input_obj=0,
                output_obj=1,
            ),
        )
    )

    finalized = finalize.finalize_placement(placement)

    assert finalized.stats["area_segments"] == 8.0
    assert finalized.stats["band_rotated"] == 0.0


def test_freeform_uses_shared_planet_finalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout.freeform import FreeformLayout

    calls: list[Placement] = []
    original = finalize.finalize_placement

    def observed(placement: Placement) -> Placement:
        calls.append(placement)
        return original(placement)

    monkeypatch.setattr(
        "flab2bp.layout.freeform.finalize.finalize_placement",
        observed,
    )
    placement = FreeformLayout(power=False).lay_out(
        two_stage_spec(),
        time_budget_s=0.5,
    )

    assert calls
    assert placement.stats["area_segments"] == float(original(placement).stats["area_segments"])


def test_sequence_pair_uses_shared_planet_finalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from flab2bp.layout.sequence_solver import SequencePairLayout

    raw = Placement(buildings=_extent(43, 35))
    calls: list[Placement] = []

    def observed(placement: Placement) -> Placement:
        calls.append(placement)
        stats = placement.stats.copy()
        stats["area_segments"] = 160.0
        stats["band_rotated"] = 0.0
        return replace(placement, stats=stats)

    class _Solver:
        def search(self) -> object:
            return SimpleNamespace(placement=raw)

    def factory(*_args: object, **_kwargs: object) -> _Solver:
        return _Solver()

    monkeypatch.setattr(
        "flab2bp.layout.sequence_solver.finalize.finalize_placement",
        observed,
    )
    placement = SequencePairLayout(solver_factory=factory).lay_out(
        two_stage_spec(),
        time_budget_s=0.5,
    )

    assert calls == [raw]
    assert placement.stats["area_segments"] == 160.0
