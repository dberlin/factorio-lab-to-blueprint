"""Strategy-independent labels for belts crossing the factory boundary."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from flab2bp.dsp import catalog, codec
from flab2bp.layout import markers
from flab2bp.layout.base import AreaFrame, PlacedBuilding, Placement
from flab2bp.spec import BuildSpec


def _belt(
    x: int,
    y: int,
    *,
    item: str,
    output: int | None,
    input_obj: int | None = None,
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
        input_obj=input_obj,
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


def test_splitter_port_belts_are_not_encoded_as_external_endpoints() -> None:
    splitter = catalog.building(catalog.SPLITTER_ID)
    placement = Placement(
        buildings=(
            PlacedBuilding(
                item_id=catalog.SPLITTER_ID,
                model_index=splitter.model_index,
                x=2,
                y=2,
            ),
            # A branch originating at the Splitter has no belt predecessor.
            _belt(2, 2, item="iron-ingot", input_obj=0, output=None),
            # A one-tile run terminating at the Splitter has no belt predecessor either.
            _belt(2, 2, item="iron-ingot", output=0),
            _belt(0, 0, item="iron-ingot", output=None),
            PlacedBuilding(item_id=0, model_index=0, x=0, y=1),
            _sorter(source=4, destination=6, item="gear"),
            _belt(4, 1, item="gear", output=None),
            PlacedBuilding(item_id=0, model_index=0, x=0, y=2),
            _sorter(source=7, destination=9, item="gear"),
            # A producer-fed output run ending at the Splitter is not an exposed tail.
            _belt(2, 2, item="gear", output=0),
        ),
        frame=AreaFrame(10, 4, 4, (4,), False),
    )
    spec = BuildSpec(
        groups=(),
        external_inputs={"iron-ingot": Fraction(1)},
        outputs={"gear": Fraction(1)},
    )

    marked = markers.mark_external_belts(placement, spec)
    decoded = codec.decode(codec.encode(marked, timestamp=0))

    assert decoded.buildings[0].parameters == ()
    assert decoded.buildings[1].parameters == ()
    assert decoded.buildings[2].parameters == ()
    assert decoded.buildings[3].parameters == catalog.belt_marker(
        catalog.item_id("iron-ingot")
    )
    assert decoded.buildings[6].parameters == catalog.belt_marker(catalog.item_id("gear"))
    assert decoded.buildings[9].parameters == ()
    assert marked.stats.get("input_markers") == 1
