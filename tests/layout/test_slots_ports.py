"""The exact in-collider question the paste asks, shared by emitter and tests."""

from __future__ import annotations

from dataclasses import replace

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import codec, colliders
from flab2bp.layout import slots
from flab2bp.layout.base import Facing, PlacedBuilding


def _host(item_id: int, yaw: float = 0.0) -> PlacedBuilding:
    info = cat.building(item_id)
    return PlacedBuilding(
        item_id=info.item_id,
        model_index=info.model_index,
        x=0,
        y=0,
        width=info.width,
        height=info.height,
        yaw=yaw,
    )


def test_the_tower_box_reaches_three_tiles_and_no_further() -> None:
    """2209's belt-height collider is the 3.9 tower, not the 5.85 cap.

    Read from the data, never from the 9x9 footprint: the exchanger's boxes are
    a cap 5.8..9.9 units up, which a belt probe at 0.4 never reaches, and a
    tower whose 3.9 / 1.2566 = 3.10 tiles it does.  So dx=3 is inside and dx=4
    is not, on both axes.
    """
    host = _host(cat.ENERGY_EXCHANGER_ID)
    centre_x, centre_y = 4, 4
    assert slots.belt_tile_hits_collider(host, centre_x + 3, centre_y)
    assert slots.belt_tile_hits_collider(host, centre_x + 3, centre_y + 3)
    assert not slots.belt_tile_hits_collider(host, centre_x + 4, centre_y)
    assert not slots.belt_tile_hits_collider(host, centre_x + 3, centre_y + 4)


def test_the_east_dock_is_inside_its_own_hosts_collider() -> None:
    """The game's own port pose sits under the building.  Not a defect."""
    host = _host(cat.ENERGY_EXCHANGER_ID)
    dock = next(d for d in slots.port_docks(host).values() if d.facing is Facing.EAST)
    assert dock.cell == (6, 4)
    assert slots.belt_tile_hits_collider(host, *dock.cell)


def test_a_storage_tank_dock_clears_its_own_collider() -> None:
    """The contrast case: a belt-port host that never needed this fix.

    An assembler is NOT the control -- cat.building(2303).port_poses is (), so
    it never takes this path at all and a test on it proves nothing.
    """
    host = _host(2106)  # Storage Tank, 3x3, east dock (2, 1)
    dock = next(d for d in slots.port_docks(host).values() if d.facing is Facing.EAST)
    assert dock.cell == (2, 1)
    assert not slots.belt_tile_hits_collider(host, dock.cell[0] + 1, dock.cell[1])


def test_the_game_rescues_the_dock_and_the_two_belts_behind_it() -> None:
    """MAX_RESCUED_COLLIDER_TILES is the paste's answer, not our number.

    Diagnosis 3.3's run, rebuilt: a column at dx=+3 climbing the exchanger,
    turning west into the east dock.  The paste convicts everything more than
    three hops from the host.  Belt (7, 0) is at dy=-4 and does not overlap at
    all, so of the six belts, 4/5/6 are rescued and 2/3 are convicted.
    """
    belt_model = cat.building(2002).model_index
    buildings = [_host(cat.ENERGY_EXCHANGER_ID)]
    buildings += [
        PlacedBuilding(item_id=2002, model_index=belt_model, x=7, y=y, width=1, height=1)
        for y in range(0, 5)
    ]
    buildings.append(
        PlacedBuilding(item_id=2002, model_index=belt_model, x=6, y=4, width=1, height=1)
    )
    for i in range(1, 6):
        buildings[i] = replace(buildings[i], output_obj=i + 1)
    buildings[6] = replace(buildings[6], output_obj=0)
    previews = tuple(
        colliders.Preview(
            b.model_index,
            *codec.tile_to_local_offset(b.x, b.y, b.z, b.width, b.height),
            b.yaw,
            is_belt=cat.is_belt(b.item_id),
            output=b.output_obj,
            input=b.input_obj,
        )
        for b in buildings
    )
    convicted = {belt for belt, _other in colliders.belt_collisions(previews)}
    assert convicted == {2, 3}
    inside = [
        i
        for i, b in enumerate(buildings)
        if i and slots.belt_tile_hits_collider(buildings[0], b.x, b.y)
    ]
    assert len(inside) - len(convicted) == slots.MAX_RESCUED_COLLIDER_TILES
