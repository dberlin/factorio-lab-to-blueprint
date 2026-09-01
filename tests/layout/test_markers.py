"""Strategy-independent labels for belts crossing the factory boundary."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout import markers
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.spec import BuildSpec


def _belt(
    x: int,
    y: int,
    *,
    item: str,
    output: int | None,
    parameters: tuple[int, ...] = (),
) -> PlacedBuilding:
    item_id = min(catalog.BELT_IDS)
    return PlacedBuilding(
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=x,
        y=y,
        z=Fraction(),
        output_obj=output,
        parameters=parameters,
        carries_item=item,
    )


def _sorter(*, source: int, destination: int, item: str) -> PlacedBuilding:
    item_id = min(catalog.SORTER_IDS)
    return PlacedBuilding(
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=0,
        y=1,
        x2=0,
        y2=2,
        input_obj=source,
        output_obj=destination,
        carries_item=item,
    )


def test_marks_external_input_heads_and_output_tails_without_touching_other_belts() -> None:
    placement = Placement(
        buildings=(
            PlacedBuilding(item_id=0, model_index=0, x=0, y=0),
            _sorter(source=0, destination=2, item="gear"),
            _belt(0, 2, item="gear", output=3),
            _belt(1, 2, item="gear", output=None),
            _belt(0, 3, item="gear", output=5),
            _belt(1, 3, item="gear", output=None),
            _belt(0, 4, item="iron-ingot", output=7),
            _belt(1, 4, item="iron-ingot", output=None),
            _belt(
                0,
                5,
                item="magnetic-coil",
                output=None,
                parameters=(9999, 0),
            ),
        )
    )
    spec = BuildSpec(
        groups=(),
        external_inputs={"iron-ingot": Fraction(1)},
        outputs={"gear": Fraction(1)},
    )

    marked = markers.mark_external_belts(placement, spec)

    assert marked.buildings[6].parameters == catalog.belt_marker(
        catalog.item_id("iron-ingot")
    )
    assert marked.buildings[3].parameters == catalog.belt_marker(catalog.item_id("gear"))
    assert marked.buildings[2].parameters == ()
    assert marked.buildings[4].parameters == ()
    assert marked.buildings[5].parameters == ()
    assert marked.buildings[8] == placement.buildings[8]
    assert tuple(replace(b, parameters=()) for b in marked.buildings[:8]) == tuple(
        replace(b, parameters=()) for b in placement.buildings[:8]
    )
    assert marked.stats["input_markers"] == 1
