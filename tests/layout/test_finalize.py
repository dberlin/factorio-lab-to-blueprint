"""Strategy-independent exact cleanup of emitted placements."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
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
