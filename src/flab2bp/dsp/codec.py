"""Top-level blueprint codec: text in, structure out, and back again."""

from __future__ import annotations

import time
from fractions import Fraction

from flab2bp.dsp import planet
from flab2bp.dsp.envelope import (
    BlueprintFormatError,
    build_envelope,
    dotnet_ticks,
    parse_envelope,
)
from flab2bp.dsp.reader import BinaryReader
from flab2bp.dsp.records import (
    Blueprint,
    BlueprintArea,
    BlueprintBuilding,
    BlueprintHeader,
    read_area,
    read_building,
    write_area,
    write_building,
)
from flab2bp.dsp.writer import BinaryWriter
from flab2bp.layout.base import Placement

#: Game version stamped on blueprints we generate.
DEFAULT_GAME_VERSION = "0.10.34.28529"
#: Payload version. 1 avoids the trailing patch/terrain-reform block entirely.
DEFAULT_PAYLOAD_VERSION = 1
#: Header version 1 carries author/customVersion/attributes.
DEFAULT_HEADER_VERSION = 1


def decode(text: str) -> Blueprint:
    """Parse a ``BLUEPRINT:`` string into structure.

    Raises :class:`BlueprintFormatError` for anything malformed, including
    Dyson-sphere (``DYBP:``) blueprints, which are a different format.
    """
    env = parse_envelope(text)
    r = BinaryReader(env.payload)

    try:
        version = r.i32()
        cursor_offset_x = r.i32()
        cursor_offset_y = r.i32()
        cursor_target_area = r.i32()
        drag_box_size_x = r.i32()
        drag_box_size_y = r.i32()
        primary_area_idx = r.i32()

        area_count = r.u8()
        # The game reports "Corrupt Data" on exactly these bounds.
        if area_count > 64 or primary_area_idx < -1 or primary_area_idx > area_count:
            raise BlueprintFormatError(
                f"Corrupt Data: areaCount={area_count} primaryAreaIdx={primary_area_idx}"
            )
        areas = tuple(read_area(r) for _ in range(area_count))

        building_count = r.i32()
        if building_count < 0 or building_count > 1_048_576:
            raise BlueprintFormatError(f"Corrupt Data: buildingCount={building_count}")
        buildings = tuple(read_building(r) for _ in range(building_count))

        patch: int | None = None
        has_reform_data = 0
        if version >= 2:
            patch = r.i32()
            has_reform_data = r.u8()

        trailing = r.rest()
    except ValueError as exc:
        raise BlueprintFormatError(f"Corrupt blueprint payload: {exc}") from exc

    return Blueprint(
        header=env.header,
        hash_valid=env.hash_valid,
        version=version,
        cursor_offset_x=cursor_offset_x,
        cursor_offset_y=cursor_offset_y,
        cursor_target_area=cursor_target_area,
        drag_box_size_x=drag_box_size_x,
        drag_box_size_y=drag_box_size_y,
        primary_area_idx=primary_area_idx,
        areas=areas,
        buildings=buildings,
        patch=patch,
        has_reform_data=has_reform_data,
        trailing=trailing,
        gzip_os=env.gzip_os,
        gzip_xfl=env.gzip_xfl,
        gzip_mtime=env.gzip_mtime,
    )


def build_payload(bp: Blueprint) -> bytes:
    """Serialise a blueprint's binary payload."""
    w = BinaryWriter()
    w.i32(bp.version)
    w.i32(bp.cursor_offset_x)
    w.i32(bp.cursor_offset_y)
    w.i32(bp.cursor_target_area)
    w.i32(bp.drag_box_size_x)
    w.i32(bp.drag_box_size_y)
    w.i32(bp.primary_area_idx)

    w.u8(len(bp.areas))
    for a in bp.areas:
        write_area(w, a)

    w.i32(len(bp.buildings))
    for b in bp.buildings:
        write_building(w, b)

    if bp.version >= 2:
        w.i32(bp.patch or 0)
        w.u8(bp.has_reform_data)

    w.raw(bp.trailing)
    return w.getvalue()


def encode_blueprint(bp: Blueprint) -> str:
    """Serialise a blueprint back to a ``BLUEPRINT:`` string.

    For a blueprint obtained from :func:`decode` this reproduces the original
    string byte for byte, hash included.
    """
    return build_envelope(
        bp.header,
        build_payload(bp),
        gzip_os=bp.gzip_os,
        gzip_xfl=bp.gzip_xfl,
        gzip_mtime=bp.gzip_mtime,
        raw_cells=bp.header.raw_cells or None,
    )


# ---------------------------------------------------------------------------
# Placement -> blueprint
# ---------------------------------------------------------------------------


def tile_to_local_offset(
    x: int, y: int, z: Fraction, width: int, height: int
) -> tuple[float, float, float]:
    """Convert an integer tile-space anchor to DSP's float ``localOffset``.

    ``(x, y)`` is the footprint's minimum corner -- the same convention
    :class:`flab2bp.layout.base.Placement` uses, where a building's tiles are
    ``range(width)`` from ``x`` -- and DSP stores the footprint *centre*, so the
    centre sits half a footprint further along each axis.  ``z`` is altitude and
    passes through unchanged.

    **Verified against the corpus**, by ``tests/dsp/test_local_offset.py``.  The
    round-trip tests could never reach this function -- they replay *decoded*
    structures, so ``decode(encode(decoded))`` is byte-perfect whatever the rule
    says -- but a blueprint the game emitted is necessarily legal, and that is a
    real oracle.  On the three fixtures with no latitude compression (3,038
    buildings; the other seven collapse distinct tiles onto one coordinate and
    are unusable for geometry) the centre reading gives:

    * **0** overlapping cells, against 18 and 38 for the two corner readings;
    * **0 of 2,656** belts inside a machine footprint, against 675 and 669;
    * **686 of 686** machine-side sorter endpoints inside the machine they
      serve, against 248/676 and 174/666.

    The sorter check is the one that pins the *offset* rather than the parity: a
    sorter endpoint is a 1x1 anchor against a 3x3 or 5x5 machine, and the
    readings differ by exactly ``(w - 1) / 2`` there.  Confirmed at footprint
    sizes 1, 3, 5 and 9.

    The even-footprint half-tile case is a different matter: it is
    **unreachable**, not verified.  ``catalog.derive_footprint`` returns
    ``2 * ceil(e / GRID_ARC) - 1``, which cannot be even, and there is no
    override table left to smuggle one in -- so ``width / 2 - 0.5`` is always
    the integer ``(width - 1) / 2`` for anything that can be placed, and the
    corpus says nothing about the branch.
    ``test_no_catalog_footprint_is_even`` fails if that ever stops being true.

    That the branch stays unreachable is a **result**, not an accident waiting
    to be corrected.  ``docs/BACKLOG.md`` once proposed making footprints the
    spacing figure ``ceil(box / GRID_ARC)``, which is EVEN for an Assembling
    Machine, on the ground that the right question is how far apart two of them
    must be.  It is the right question -- and it already has an answer,
    ``catalog.clearance``, which the packers use.  Answering it *here* as well
    would put an assembler's centre on a half-tile, and across the geometry
    corpus 3,038 of 3,038 buildings are integer-centred.  The game does not
    write that geometry; neither may we.
    """
    return (x + width / 2.0 - 0.5, y + height / 2.0 - 0.5, float(z))


def _area_for(placement: Placement) -> BlueprintArea:
    """The single area record, with the band this extent actually belongs to.

    ``area_segments`` was the literal 200 for every blueprint we have ever
    written, which says "this was copied from the equatorial band" whatever the
    extent is.  The game writes the band it copied FROM
    (``BlueprintUtils.cs:1426``), and :func:`flab2bp.dsp.planet.band_for_extent`
    is the same quantisation run forwards: the smallest band the extent fits, in
    either orientation.

    A strategy that has VERIFIED which band its layout pastes in records the
    answer in ``stats["area_segments"]`` and that wins, because it is a stronger
    claim: the extent-only answer says the area fits, the verified one says the
    game accepts it.  ``layout.spine._band_rejected`` is what sets it.  Without
    it the extent is all there is to go on.

    An extent that fits NO band raises :class:`~flab2bp.dsp.planet.BandRefusal`
    rather than falling back to 200.  Such a blueprint crosses a tropic at every
    anchor on the planet and the game refuses it with
    ``EBuildCondition.BlueprintAreaCrossTropic``; writing 200 would encode a
    blueprint that cannot be pasted anywhere and say nothing about it.
    """
    min_x, min_y, max_x, max_y = placement.bounds
    width = max(1, max_x - min_x + 1)
    height = max(1, max_y - min_y + 1)
    verified = placement.stats.get("area_segments")
    return BlueprintArea(
        index=0,
        parent_index=-1,
        tropic_anchor=0,
        area_segments=(
            int(verified)
            if verified is not None
            else planet.band_for_extent(width, height).band.area_segments
        ),
        anchor_local_offset_x=0,
        anchor_local_offset_y=0,
        width=width,
        height=height,
    )


def placement_to_blueprint(
    placement: Placement,
    *,
    game_version: str = DEFAULT_GAME_VERSION,
    author: str = "flab2bp",
    timestamp: int | None = None,
) -> Blueprint:
    """Turn a :class:`Placement` into an encodable :class:`Blueprint`.

    List position becomes the DSP building ``index``, and ``None`` connections
    become ``-1``.
    """
    buildings: list[BlueprintBuilding] = []
    for i, b in enumerate(placement.buildings):
        x, y, z = tile_to_local_offset(b.x, b.y, b.z, b.width, b.height)
        if b.x2 is None:
            x2, y2, z2 = x, y, z
        else:
            x2, y2, z2 = tile_to_local_offset(
                b.x2, b.y2 or 0, b.z2 if b.z2 is not None else Fraction(0), 1, 1
            )
        buildings.append(
            BlueprintBuilding(
                # Path == index selects the simplest record shape, which every
                # game version reads.
                path=i,
                index=i,
                area_index=0,
                item_id=b.item_id,
                model_index=b.model_index,
                x=x,
                y=y,
                z=z,
                x2=x2,
                y2=y2,
                z2=z2,
                yaw=b.yaw,
                yaw2=b.yaw2 if b.yaw2 is not None else b.yaw,
                output_obj_idx=-1 if b.output_obj is None else b.output_obj,
                input_obj_idx=-1 if b.input_obj is None else b.input_obj,
                output_to_slot=b.output_to_slot,
                input_from_slot=b.input_from_slot,
                output_from_slot=b.output_from_slot,
                input_to_slot=b.input_to_slot,
                output_offset=b.output_offset,
                input_offset=b.input_offset,
                recipe_id=b.recipe_id,
                filter_id=b.filter_id,
                parameters=tuple(b.parameters),
            )
        )

    header = BlueprintHeader(
        header_version=DEFAULT_HEADER_VERSION,
        layout=10,
        icons=tuple(list(placement.icons)[:5] + [0] * (5 - len(placement.icons[:5]))),
        timestamp=timestamp if timestamp is not None else dotnet_ticks(time.time()),
        game_version=game_version,
        short_desc=placement.short_desc,
        author=author,
        custom_version="",
        attributes=(),
        description=placement.description,
    )

    return Blueprint(
        header=header,
        hash_valid=True,
        version=DEFAULT_PAYLOAD_VERSION,
        cursor_offset_x=0,
        cursor_offset_y=0,
        cursor_target_area=0,
        drag_box_size_x=_area_for(placement).width,
        drag_box_size_y=_area_for(placement).height,
        primary_area_idx=0,
        areas=(_area_for(placement),),
        buildings=tuple(buildings),
        gzip_os=0x0A,
    )


def encode(placement: Placement, **kwargs: object) -> str:
    """Convenience: :class:`Placement` straight to a pasteable string."""
    return encode_blueprint(placement_to_blueprint(placement, **kwargs))  # type: ignore[arg-type]
