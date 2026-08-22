"""Reader/writer symmetry on synthetic records.

The fixtures prove the common paths; these prove the ones real blueprints
happen not to exercise, so a future edit cannot silently break them.
"""

from __future__ import annotations

import math

import pytest

from flab2bp.dsp.reader import BinaryReader
from flab2bp.dsp.records import (
    BlueprintArea,
    BlueprintBuilding,
    read_area,
    read_building,
    write_area,
    write_building,
)
from flab2bp.dsp.writer import BinaryWriter

BELT_ITEM = 2003
SORTER_ITEM = 2013
ASSEMBLER_ITEM = 2304


def _building(**overrides: object) -> BlueprintBuilding:
    base: dict[str, object] = dict(
        path=7,
        index=7,
        area_index=0,
        item_id=ASSEMBLER_ITEM,
        model_index=67,
        x=1.5,
        y=-2.25,
        z=0.0,
        x2=1.5,
        y2=-2.25,
        z2=0.0,
        yaw=90.0,
        yaw2=90.0,
        output_obj_idx=-1,
        input_obj_idx=-1,
        recipe_id=61,
    )
    base.update(overrides)
    return BlueprintBuilding(**base)  # type: ignore[arg-type]


def _roundtrip(b: BlueprintBuilding) -> BlueprintBuilding:
    w = BinaryWriter()
    write_building(w, b)
    return read_building(BinaryReader(w.getvalue()))


@pytest.mark.parametrize(
    "path,item_id",
    [
        (7, ASSEMBLER_ITEM),  # layout B, index == path
        (-100, ASSEMBLER_ITEM),  # layout B with tilt
        (-101, ASSEMBLER_ITEM),  # layout A, no content
        (-101, BELT_ITEM),  # layout A, belt float block
        (-101, SORTER_ITEM),  # layout A, sorter float block
        (-102, ASSEMBLER_ITEM),  # layout A with content
    ],
)
def test_all_four_path_layouts_survive(path: int, item_id: int) -> None:
    b = _building(path=path, index=7 if path > -100 else 42, item_id=item_id)
    assert _roundtrip(b) == b


def test_sorter_second_anchor_is_preserved() -> None:
    """Layout A stores a sorter's eight extra floats; none may be dropped."""
    b = _building(
        path=-101,
        index=3,
        item_id=SORTER_ITEM,
        x2=9.5,
        y2=-4.0,
        z2=1.25,
        yaw2=270.0,
        tilt=15.0,
        tilt2=-15.0,
        pitch=5.0,
        pitch2=-5.0,
    )
    assert _roundtrip(b) == b


def test_belt_tilt_mirrors_into_second_anchor() -> None:
    """A belt stores one tilt; the reader derives the mirrored fields."""
    b = _building(path=-101, index=3, item_id=BELT_ITEM, tilt=30.0, tilt2=30.0)
    got = _roundtrip(b)
    assert got == b
    assert got.tilt2 == got.tilt
    assert (got.x2, got.y2, got.z2, got.yaw2) == (got.x, got.y, got.z, got.yaw)


def test_parameters_survive() -> None:
    b = _building(parameters=(1, -2, 3, 2**31 - 1, -(2**31)))
    assert _roundtrip(b) == b


def test_content_string_survives_non_ascii() -> None:
    """C# writes a char count and a separate LEB128 *byte* count; they differ."""
    text = "配電盤 ✦"
    assert len(text) == 5 and len(text.encode("utf-8")) == 13  # the two lengths diverge
    b = _building(path=-102, index=5, content=text)
    got = _roundtrip(b)
    assert got.content == text
    assert got.content_char_length == 5
    assert got == b


def test_content_absent_when_char_length_zero() -> None:
    b = _building(path=-102, index=5, content=None, content_char_length=0)
    assert _roundtrip(b) == b


def test_slot_fields_survive_negative_values() -> None:
    b = _building(
        output_to_slot=-1,
        input_from_slot=-1,
        output_from_slot=-3,
        input_to_slot=2,
        output_offset=-1,
        input_offset=1,
        filter_id=1104,
    )
    assert _roundtrip(b) == b


def test_float_values_are_exact_through_f32() -> None:
    """Values that are exactly representable in f32 must not drift."""
    b = _building(x=0.5, y=-16.25, z=3.125, x2=0.5, y2=-16.25, z2=3.125)
    got = _roundtrip(b)
    assert (got.x, got.y, got.z) == (0.5, -16.25, 3.125)


def test_area_roundtrip() -> None:
    a = BlueprintArea(
        index=1,
        parent_index=-1,
        tropic_anchor=-3,
        area_segments=200,
        anchor_local_offset_x=-12,
        anchor_local_offset_y=34,
        width=25,
        height=40,
    )
    w = BinaryWriter()
    write_area(w, a)
    assert read_area(BinaryReader(w.getvalue())) == a


def test_reader_rejects_read_past_end() -> None:
    r = BinaryReader(b"\x01\x02")
    with pytest.raises(ValueError):
        r.i32()


def test_writer_rejects_out_of_range() -> None:
    w = BinaryWriter()
    with pytest.raises((ValueError, OverflowError)):
        w.i16(70000)


def test_leb128_roundtrip_across_widths() -> None:
    for n in (0, 1, 127, 128, 300, 16383, 16384, 2097151, 2097152):
        w = BinaryWriter()
        w.leb(n)
        assert BinaryReader(w.getvalue()).leb() == n


def test_nan_free_defaults() -> None:
    b = _building()
    for v in (b.x, b.y, b.z, b.yaw, b.tilt, b.pitch):
        assert not math.isnan(v)
