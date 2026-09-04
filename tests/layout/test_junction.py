"""Game-code conformance tests for belt-integrated junction records."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.dsp import catalog, codec
from flab2bp.layout import junction
from flab2bp.layout.base import AreaFrame, PlacedBuilding, Placement


@pytest.mark.parametrize(
    ("yaw", "footprint", "centre"),
    [
        (0.0, (1, 3), (2.0, 3.0)),
        (90.0, (3, 1), (3.0, 2.0)),
    ],
)
def test_make_piler_uses_the_catalog_model_footprint_and_centre(
    yaw: float,
    footprint: tuple[int, int],
    centre: tuple[float, float],
) -> None:
    piler = junction.make_piler(2, 2, Fraction(1, 2), yaw=yaw)

    assert piler.item_id == catalog.PILER_ID == 2040
    assert piler.model_index == 257
    assert (piler.width, piler.height) == footprint
    assert (piler.x, piler.y, piler.z, piler.yaw) == (2, 2, Fraction(1, 2), yaw)

    record = codec.placement_to_blueprint(
        Placement(
            buildings=(piler,),
            frame=AreaFrame(6, 6, 40, (40,), False),
        ),
        timestamp=0,
    ).buildings[0]
    assert (record.x, record.y, record.z) == (*centre, 0.5)
    assert (record.x2, record.y2, record.z2) == (*centre, 0.5)
    assert (record.yaw, record.yaw2) == (yaw, yaw)


def test_piler_catalog_ports_pin_pile_mode_orientation() -> None:
    """At yaw 0, game port 0 faces north/output and port 1 south/input.

    ``CargoTraffic.RematchPilerConnection`` 0.10.34 lines 938-974 reads
    piler slots 0 and 1 and selects ``Pile`` when slot 0 is output and slot 1
    is input.  These are the shipped model-257 ``PrefabDesc.portPoses`` in the
    catalog, including their order and exact local offsets.
    """
    info = catalog.building(catalog.PILER_ID)

    assert catalog.is_belt_integrated(catalog.PILER_ID)
    assert (info.model_index, info.width, info.height) == (257, 1, 3)
    assert info.slot_poses == ()
    assert info.port_poses == (
        catalog.SlotPose(dx=0.0, dy=0.25, dz=0.0, fx=0.0, fy=1.0, fz=0.0),
        catalog.SlotPose(dx=0.0, dy=-0.25, dz=0.0, fx=0.0, fy=-1.0, fz=0.0),
    )


def test_piler_and_adjacent_belt_records_follow_game_wiring_literals() -> None:
    """Originate and decode the record shape derived from shipped game code.

    ``BlueprintUtils.GenerateBlueprintData`` 0.10.34 lines 1181-1182 and
    1222-1306 see the piler's ``multiLevel = 1`` and assign the four sentinel
    slot integers ``inputToSlot = 14``, ``outputFromSlot = 15``,
    ``inputFromSlot = 15``, and ``outputToSlot = 14`` while leaving its object
    references null. ``BlueprintBuilding.Export`` lines 294-295 writes those
    null references as -1. The belt branch at lines 1248-1272 carries the
    connections: the belt before names piler port 1, and the belt after names
    piler port 0. ``BuildingParameters.ToParamsArray`` lines 83-363 falls
    through to a zero-length parameter array for the piler.
    """
    belt = catalog.building(2003)
    piler = junction.make_piler(2, 2)
    before = PlacedBuilding(
        item_id=2003,
        model_index=belt.model_index,
        x=2,
        y=1,
        output_obj=1,
        output_to_slot=1,
    )
    after = PlacedBuilding(
        item_id=2003,
        model_index=belt.model_index,
        x=2,
        y=5,
        input_obj=1,
        input_from_slot=0,
    )

    assert piler.input_obj is None
    assert piler.output_obj is None
    assert (
        piler.input_from_slot,
        piler.input_to_slot,
        piler.output_from_slot,
        piler.output_to_slot,
    ) == (15, 14, 15, 14)
    assert piler.parameters == ()

    decoded = codec.decode(
        codec.encode(
            Placement(
                buildings=(before, piler, after),
                frame=AreaFrame(6, 7, 40, (40,), False),
            ),
            timestamp=0,
        )
    ).buildings
    before_record, piler_record, after_record = decoded

    assert (piler_record.input_obj_idx, piler_record.output_obj_idx) == (-1, -1)
    assert (
        piler_record.input_from_slot,
        piler_record.input_to_slot,
        piler_record.output_from_slot,
        piler_record.output_to_slot,
    ) == (15, 14, 15, 14)
    assert piler_record.parameters == ()
    assert (before_record.output_obj_idx, before_record.output_to_slot) == (1, 1)
    assert (after_record.input_obj_idx, after_record.input_from_slot) == (1, 0)
