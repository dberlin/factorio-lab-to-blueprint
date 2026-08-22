"""The blueprint payload's record types, and their exact binary form.

Reading is lossy in the obvious implementation -- the game's record format has
four shapes selected by a leading "path number", and several fields are derived
rather than stored -- so every field needed to reproduce the original bytes is
kept here, including the path number itself and the redundant character count
that precedes a content string.  That is what makes byte-identical re-encoding
possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from flab2bp.dsp.reader import BinaryReader
from flab2bp.dsp.writer import BinaryWriter


def is_belt(item_id: int) -> bool:
    return 2000 < item_id < 2010


def is_sorter(item_id: int) -> bool:
    return 2010 < item_id < 2020


@dataclass(frozen=True, slots=True)
class BlueprintArea:
    """A 14-byte area record. Blueprints carry at most 64."""

    index: int
    parent_index: int
    tropic_anchor: int
    area_segments: int
    anchor_local_offset_x: int
    anchor_local_offset_y: int
    width: int
    height: int


def read_area(r: BinaryReader) -> BlueprintArea:
    return BlueprintArea(
        index=r.i8(),
        parent_index=r.i8(),
        tropic_anchor=r.i16(),
        area_segments=r.i16(),
        anchor_local_offset_x=r.i16(),
        anchor_local_offset_y=r.i16(),
        width=r.i16(),
        height=r.i16(),
    )


def write_area(w: BinaryWriter, a: BlueprintArea) -> None:
    w.i8(a.index)
    w.i8(a.parent_index)
    w.i16(a.tropic_anchor)
    w.i16(a.area_segments)
    w.i16(a.anchor_local_offset_x)
    w.i16(a.anchor_local_offset_y)
    w.i16(a.width)
    w.i16(a.height)


@dataclass(frozen=True, slots=True)
class BlueprintBuilding:
    """One building.

    ``path`` is the leading i32 that selects the record shape:

    ==========  ======================================================
    ``path``    shape
    ==========  ======================================================
    ``<= -102`` layout A, followed by a content string
    ``<= -101`` layout A
    ``<= -100`` layout B, with an extra ``tilt``
    otherwise   layout B, and ``path`` *is* the building index
    ==========  ======================================================

    It is stored rather than recomputed because the choice is the game's, and
    re-deriving it would change bytes on re-encode.
    """

    path: int
    index: int
    area_index: int
    item_id: int
    model_index: int

    x: float
    y: float
    z: float
    x2: float
    y2: float
    z2: float
    yaw: float
    yaw2: float
    tilt: float = 0.0
    tilt2: float = 0.0
    pitch: float = 0.0
    pitch2: float = 0.0

    output_obj_idx: int = -1
    input_obj_idx: int = -1
    output_to_slot: int = 0
    input_from_slot: int = 0
    output_from_slot: int = 0
    input_to_slot: int = 0
    output_offset: int = 0
    input_offset: int = 0
    recipe_id: int = 0
    filter_id: int = 0
    parameters: tuple[int, ...] = ()

    content: str | None = None
    #: The redundant char count C# writes before the string. Derived from
    #: ``content`` when not given; stored because for non-ASCII text it differs
    #: from the LEB128 *byte* length that follows it.
    content_char_length: int | None = None

    def __post_init__(self) -> None:
        if self.content_char_length is None:
            object.__setattr__(
                self, "content_char_length", len(self.content) if self.content else 0
            )


def read_building(r: BinaryReader) -> BlueprintBuilding:
    path = r.i32()

    tilt = tilt2 = pitch = pitch2 = 0.0

    if path <= -101:
        # Layout A: identity first, then a single anchor, then a
        # class-dependent float block.
        index = r.i32()
        item_id = r.i16()
        model_index = r.i16()
        area_index = r.i8()
        x, y, z, yaw = r.f32(), r.f32(), r.f32(), r.f32()

        if is_belt(item_id):
            tilt = r.f32()
            x2, y2, z2, yaw2, tilt2 = x, y, z, yaw, tilt
        elif is_sorter(item_id):
            tilt = r.f32()
            pitch = r.f32()
            x2, y2, z2 = r.f32(), r.f32(), r.f32()
            yaw2, tilt2, pitch2 = r.f32(), r.f32(), r.f32()
        else:
            x2, y2, z2, yaw2 = x, y, z, yaw
    else:
        # Layout B: both anchors always present; identity last.
        index = r.i32() if path <= -100 else path
        area_index = r.i8()
        x, y, z = r.f32(), r.f32(), r.f32()
        x2, y2, z2 = r.f32(), r.f32(), r.f32()
        yaw, yaw2 = r.f32(), r.f32()
        if path <= -100:
            tilt = r.f32()
        item_id = r.i16()
        model_index = r.i16()

    output_obj_idx = r.i32()
    input_obj_idx = r.i32()
    output_to_slot = r.i8()
    input_from_slot = r.i8()
    output_from_slot = r.i8()
    input_to_slot = r.i8()
    output_offset = r.i8()
    input_offset = r.i8()
    recipe_id = r.i16()
    filter_id = r.i16()

    param_count = r.i16()
    if param_count < 0 or param_count > 32768:
        raise ValueError(f"Corrupt Data: implausible parameter count {param_count}")
    parameters = tuple(r.i32() for _ in range(param_count))

    content: str | None = None
    content_char_length: int | None = None
    if path <= -102:
        content_char_length = r.i32()
        if content_char_length > 0:
            content = r.string()

    return BlueprintBuilding(
        path=path,
        index=index,
        area_index=area_index,
        item_id=item_id,
        model_index=model_index,
        x=x,
        y=y,
        z=z,
        x2=x2,
        y2=y2,
        z2=z2,
        yaw=yaw,
        yaw2=yaw2,
        tilt=tilt,
        tilt2=tilt2,
        pitch=pitch,
        pitch2=pitch2,
        output_obj_idx=output_obj_idx,
        input_obj_idx=input_obj_idx,
        output_to_slot=output_to_slot,
        input_from_slot=input_from_slot,
        output_from_slot=output_from_slot,
        input_to_slot=input_to_slot,
        output_offset=output_offset,
        input_offset=input_offset,
        recipe_id=recipe_id,
        filter_id=filter_id,
        parameters=parameters,
        content=content,
        content_char_length=content_char_length,
    )


def write_building(w: BinaryWriter, b: BlueprintBuilding) -> None:
    w.i32(b.path)

    if b.path <= -101:
        w.i32(b.index)
        w.i16(b.item_id)
        w.i16(b.model_index)
        w.i8(b.area_index)
        w.f32(b.x)
        w.f32(b.y)
        w.f32(b.z)
        w.f32(b.yaw)

        if is_belt(b.item_id):
            # The mirrored anchor and tilt2 are derived on read, not stored.
            w.f32(b.tilt)
        elif is_sorter(b.item_id):
            w.f32(b.tilt)
            w.f32(b.pitch)
            w.f32(b.x2)
            w.f32(b.y2)
            w.f32(b.z2)
            w.f32(b.yaw2)
            w.f32(b.tilt2)
            w.f32(b.pitch2)
    else:
        if b.path <= -100:
            w.i32(b.index)
        w.i8(b.area_index)
        w.f32(b.x)
        w.f32(b.y)
        w.f32(b.z)
        w.f32(b.x2)
        w.f32(b.y2)
        w.f32(b.z2)
        w.f32(b.yaw)
        w.f32(b.yaw2)
        if b.path <= -100:
            w.f32(b.tilt)
        w.i16(b.item_id)
        w.i16(b.model_index)

    w.i32(b.output_obj_idx)
    w.i32(b.input_obj_idx)
    w.i8(b.output_to_slot)
    w.i8(b.input_from_slot)
    w.i8(b.output_from_slot)
    w.i8(b.input_to_slot)
    w.i8(b.output_offset)
    w.i8(b.input_offset)
    w.i16(b.recipe_id)
    w.i16(b.filter_id)

    w.i16(len(b.parameters))
    for p in b.parameters:
        w.i32(p)

    if b.path <= -102:
        char_length = b.content_char_length or 0
        w.i32(char_length)
        if char_length > 0:
            w.string(b.content or "")


@dataclass(frozen=True, slots=True)
class BlueprintHeader:
    """The CSV header ahead of the payload.

    ``raw_cells`` keeps the header exactly as it arrived.  Text fields are
    percent-encoded, and re-encoding a decoded string does not always reproduce
    the original bytes, so re-emission replays the raw cells and the decoded
    fields exist purely for callers to read.
    """

    header_version: int
    layout: int
    icons: tuple[int, ...]
    timestamp: int
    game_version: str
    short_desc: str
    author: str = ""
    custom_version: str = ""
    attributes: tuple[str, ...] = ()
    description: str = ""
    raw_cells: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Blueprint:
    """A fully decoded blueprint, carrying everything re-encoding needs."""

    header: BlueprintHeader
    hash_valid: bool
    version: int
    cursor_offset_x: int
    cursor_offset_y: int
    cursor_target_area: int
    drag_box_size_x: int
    drag_box_size_y: int
    primary_area_idx: int
    areas: tuple[BlueprintArea, ...]
    buildings: tuple[BlueprintBuilding, ...]

    #: Present only when ``version >= 2``.
    patch: int | None = None
    has_reform_data: int = 0
    #: Bytes trailing the parsed payload, replayed verbatim on re-encode.
    trailing: bytes = b""
    #: gzip OS byte, which varies by the game build that wrote the blueprint
    #: (0x0b for header version 0, 0x0a for version 1 in the observed corpus).
    gzip_os: int = 0x0B
    gzip_xfl: int = 0x00
    gzip_mtime: int = 0
    extra: dict[str, object] = field(default_factory=dict)
