"""The exact in-collider question the paste asks, shared by emitter and tests."""

from __future__ import annotations

from dataclasses import replace

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import codec, colliders
from flab2bp.layout import freeform, slots
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


def test_the_exchanger_approach_turns_outside_the_tower() -> None:
    """Dock at dx=+2, tower reach dx=+3: turn at +4, not +3.

    Turning at +3 puts the whole vertical run inside the collider (measured:
    five tiles, three rescued, two convicted).  Turning at +4 puts only
    (+3, dock row) and the dock inside -- two, one under the budget, and
    CONTIGUOUS with the port, which is what the rescue actually requires.
    """
    host = _host(cat.ENERGY_EXCHANGER_ID)
    dock = next(d for d in slots.port_docks(host).values() if d.facing is Facing.EAST)
    result = freeform._port_approach(host, dock, 12, range(-4, 24), host.width + 2)
    assert result is not None
    cells, tap_x = result
    assert tap_x == dock.cell[0] + 2
    assert cells[-1] == dock.cell
    inside = [c for c in cells if slots.belt_tile_hits_collider(host, *c)]
    assert len(inside) == 2
    assert cells[-2:] == inside  # a SUFFIX, not merely few


def test_a_storage_tank_approach_still_taps_one_column_east() -> None:
    """A belt-port host whose dock clears its collider does not move at all."""
    host = _host(2106)  # Storage Tank, 3x3, east dock (2, 1)
    dock = next(d for d in slots.port_docks(host).values() if d.facing is Facing.EAST)
    result = freeform._port_approach(host, dock, 6, range(-4, 20), host.width + 2)
    assert result is not None
    _cells, tap_x = result
    assert tap_x == dock.cell[0] + 1


def test_a_ray_receiver_east_dock_is_inside_its_own_collider() -> None:
    """2208's tap+1 is inside its collider at yaw 90; the rule generalises.

    Ray Receivers have no INPUT lanes today and no east dock at yaw 0, so
    _dock_input_lane never runs for one.  This pins the predicate's answer, not
    a behaviour change -- universe-matrix places 8-10 of them and nothing here
    may move that placement.
    """
    host = _host(cat.RAY_RECEIVER_ID, yaw=90.0)
    dock = next(d for d in slots.port_docks(host).values() if d.facing is Facing.EAST)
    assert dock.cell == (4, 3)
    assert slots.belt_tile_hits_collider(host, dock.cell[0] + 1, dock.cell[1])


def test_the_reserved_pitch_contains_the_tap_column_for_every_belt_port_host() -> None:
    """freeform.py:2216 buys one spare column for a port-input host.  Enough?

    An invariant, not two samples: this test is what licenses skipping the
    pitch work entirely, so it asks every belt-port host in the catalog at
    every yaw.  Measured on 688cbed it holds for all eight (2020 Splitter,
    2040 Automatic Piler, 2103/2104 Logistics Stations, 2106 Storage Tank,
    2208 Ray Receiver, 2209 Energy Exchanger, 2301/2306/2307/2314/2316), for
    every yaw with an east dock; the exchanger is yaw-invariant because its
    footprint is square.  If a future host ever needs more, this fails and the
    fix is MachinePlacementGeometry.with_minimum_pitch_x, not a wider lane trim.
    """
    hosts = [
        building.item_id
        for building in cat.all_buildings()  # the real accessor
        if building.port_poses and not building.slot_poses
    ]
    assert cat.ENERGY_EXCHANGER_ID in hosts and 2106 in hosts, hosts
    checked = 0
    for item_id in hosts:
        for yaw in (0.0, 90.0, 180.0, 270.0):
            pitch_w = cat.clearance(item_id, yaw)[0] + 1  # the port_inputs column
            probe = slots.probe_building(item_id, yaw)
            for dock in slots.port_docks(probe).values():
                if dock.facing is not Facing.EAST:
                    continue
                offset = freeform._port_approach_offset(probe, dock, pitch_w)
                assert offset is not None, (item_id, yaw, dock)
                assert dock.cell[0] + offset < pitch_w, (item_id, yaw, dock, offset, pitch_w)
                checked += 1
    assert checked >= 8, checked  # not vacuous
