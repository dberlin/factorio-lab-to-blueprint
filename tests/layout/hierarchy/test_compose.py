import re
import time
from fractions import Fraction
from typing import NamedTuple

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout import junction, slots
from flab2bp.layout.base import Facing, PlacedBuilding, Placement
from flab2bp.layout.hierarchy import compose
from flab2bp.layout.hierarchy.contracts import LaneFlow
from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    NetFailure,
    RouteFailureKind,
)
from flab2bp.spec import BuildSpec
from tests.layout.hierarchy.conftest import chain_build_spec

TwoSolvedBlocks = tuple[Placement, Placement, list[LaneFlow], BuildSpec, bool]


def test_pack_blocks_keeps_a_two_tile_gap_and_prefers_a_band_legal_shape():
    sizes = [(40, 30), (40, 30), (40, 30), (40, 30)]
    offsets, width, height = compose.pack_blocks(sizes, gap=2)
    boxes = [(x, y, x + w, y + h) for (x, y), (w, h) in zip(offsets, sizes, strict=True)]
    for a in range(4):
        for b in range(a + 1, 4):
            ax0, ay0, ax1, ay1 = boxes[a]
            bx0, by0, bx1, by1 = boxes[b]
            assert ax1 + 2 <= bx0 or bx1 + 2 <= ax0 or ay1 + 2 <= by0 or by1 + 2 <= ay0
    assert min(width, height) <= 160


def test_pack_blocks_never_exceeds_160_rows_when_a_legal_shape_exists():
    sizes = [(30, 60)] * 8
    _offsets, width, height = compose.pack_blocks(sizes, gap=2)
    assert min(width, height) <= 160


class MixedBlock(NamedTuple):
    """A hand-built composed block holding one of every registration kind."""

    buildings: list[PlacedBuilding]
    sorter: PlacedBuilding
    splitter: PlacedBuilding
    machine: PlacedBuilding
    coaters: list[PlacedBuilding]
    drops: list[tuple[int, int, int]]


def _coater(x: int, y: int) -> PlacedBuilding:
    return PlacedBuilding(
        item_id=catalog.SPRAY_COATER_ID,
        model_index=catalog.building(catalog.SPRAY_COATER_ID).model_index,
        x=x,
        y=y,
        z=Fraction(0),
        width=1,
        height=1,
        yaw=Facing.EAST.value,
    )


def _drop_of(coater: PlacedBuilding) -> tuple[int, int, int]:
    return slots.addon_supply_cell(
        catalog.SPRAY_COATER_ID, x=coater.x, y=coater.y, z=coater.z, yaw=coater.yaw, area=1
    )


def _mixed_block(*, coater_seats: tuple[int, ...]) -> MixedBlock:
    """A lane with a Splitter on it, ``coater_seats`` Coaters, a sorter, a machine."""
    spec = chain_build_spec()
    belt_id = catalog.get_item_id(spec.belt_item_id) or 2001
    belt_model = catalog.building(belt_id).model_index
    coaters = [_coater(x, 0) for x in coater_seats]
    drops = [_drop_of(c) for c in coaters]
    # The host lane on the ground, plus each Coater's supply pair at the drop's
    # own altitude -- which is a level up, not a tile across.
    cells = [(x, 0, Fraction(0)) for x in range(8)]
    for coater, drop in zip(coaters, drops, strict=True):
        approach = (2 * drop[0] - coater.x, 2 * drop[1] - coater.y)
        cells.append((drop[0], drop[1], Fraction(drop[2])))
        cells.append((approach[0], approach[1], Fraction(drop[2])))
    buildings = [
        PlacedBuilding(
            item_id=belt_id,
            model_index=belt_model,
            x=x,
            y=y,
            z=z,
            width=1,
            height=1,
            carries_item="iron-ingot",
        )
        for x, y, z in dict.fromkeys(cells)
    ]
    splitter = junction.make_splitter(6, 0, Fraction(0))
    buildings.append(splitter)
    sorter = PlacedBuilding(
        item_id=catalog.SORTER_TIERS[0],
        model_index=catalog.building(catalog.SORTER_TIERS[0]).model_index,
        x=2,
        y=4,
        width=1,
        height=1,
    )
    buildings.append(sorter)
    machine_id = catalog.get_item_id("arc-smelter")
    assert machine_id is not None
    catalog_machine = catalog.building(machine_id)
    machine = PlacedBuilding(
        item_id=machine_id,
        model_index=catalog_machine.model_index,
        x=8,
        y=6,
        width=catalog_machine.width,
        height=catalog_machine.height,
        recipe_id=1,
    )
    buildings.append(machine)
    buildings.extend(coaters)
    return MixedBlock(buildings, sorter, splitter, machine, coaters, drops)


def test_canvas_for_registers_each_building_kind_the_way_freeform_does():
    """Kind by kind, because the differences are what the game enforces.

    A composed canvas that marks a sorter solid costs the router paths the game
    allows; one that leaves a Splitter unguarded lets a cut route run through a
    collider cross that reports no occupied tile; one that never prices a
    Coater's collider lets the router lay a level-1 belt beside it that the game
    refuses on paste.
    """
    block = _mixed_block(coater_seats=(3,))
    canvas = compose.canvas_for(chain_build_spec(), block.buildings, ramped=False, margin=4)

    # Index order is the composed list's own: every `_Port` indexes into it.
    assert canvas.buildings == block.buildings

    assert (block.sorter.x, block.sorter.y) not in canvas.solid
    assert not any(key[:2] == (block.sorter.x, block.sorter.y) for key in canvas.blocked)

    assert (block.machine.x, block.machine.y) in canvas.solid
    assert any(key[:2] == (block.machine.x, block.machine.y) for key in canvas.blocked)

    splitter = block.splitter
    keepout = set(
        junction.keepout_cells(
            splitter.x,
            splitter.y,
            int(splitter.z),
            model_index=splitter.model_index,
            yaw=splitter.yaw,
        )
    )
    assert keepout, "the fixture's Splitter must deny some cell"
    assert keepout <= canvas.guard
    assert (splitter.x, splitter.y) not in canvas.solid

    coater = block.coaters[0]
    assert canvas.belt_ban, "a composed Coater must price its own collider"
    banned = set(canvas.belt_ban)
    assert any(abs(x - coater.x) <= 2 and abs(y - coater.y) <= 2 for x, y in banned)
    assert all(levels and min(levels) >= 1 for levels in canvas.belt_ban.values())


def test_a_coater_drop_is_exempt_from_another_coaters_ban():
    """Two Coaters one tile apart: A's ban covers B's drop, and the drop wins.

    Not a seating the placer would produce -- with the real 3x1 Coater collider
    the only tile a Coater bans is its own host tile, so one ban reaches another
    Coater's drop exactly when they stand adjacent. It is nevertheless the case
    `_place_coaters` sweeps for after staging every Coater ("every drop is
    exempt from every OVERLAPPING Coater ban"), and without that sweep the
    router is denied a cell the game requires a belt on.
    """
    alone = _mixed_block(coater_seats=(3,))
    with_peer = _mixed_block(coater_seats=(3, 4))
    peer_drop = with_peer.drops[1][:2]
    assert peer_drop == (3, 0), "the fixture's second Coater must drop onto the first"

    banned_alone = compose.canvas_for(
        chain_build_spec(), alone.buildings, ramped=False, margin=4
    ).belt_ban
    banned_both = compose.canvas_for(
        chain_build_spec(), with_peer.buildings, ramped=False, margin=4
    ).belt_ban

    assert peer_drop in banned_alone, "the first Coater must ban that cell on its own"
    assert peer_drop not in banned_both


def test_compose_routes_one_cut_between_two_solved_blocks(two_solved_blocks: TwoSolvedBlocks):
    # `two_solved_blocks` (conftest): the `chain_spec` of test_pressure split at
    # its one cut, both blocks laid out by FreeformLayout at 10 s, plus the
    # flows from assign_lanes.
    left, right, flows, spec, ramped = two_solved_blocks
    result = compose.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None)
    assert result.failures == ()
    assert result.routed == len(flows)
    heads = {f.dst.building + result.blocks[1].base for f in flows}
    fed = {b.output_obj for b in result.placement.buildings if b.output_obj is not None}
    assert heads <= fed


def test_compose_reports_an_unwired_cut_instead_of_handing_it_back(
    two_solved_blocks: TwoSolvedBlocks,
):
    """A real router verdict, not a mock: the deadline is already spent.

    `_route_all` checks its deadline between rounds AND between nets and never
    commits the live paths once it has expired, so every cut comes back
    unwired. What is under test is that they come back NAMED -- an unwired
    entry lane the composer swallowed is a block that starves, convicted many
    stages later with no way back to the cause.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    expired = compose.compose(
        [left, right], flows, spec, gap=2, ramped=ramped, deadline=time.monotonic() - 1.0
    )
    assert expired.routed < len(flows)
    assert expired.failures
    for line in expired.failures:
        assert re.fullmatch(r"\S+: block \d+ -> block \d+: [A-Z_]+", line), line
        assert "external_input" not in line


def test_a_stranded_cut_is_named_by_item_blocks_and_router_kind(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """The failure line is the only thing that survives the router's own types.

    The fixture's two blocks route on this canvas, so the reporting path is
    reached by scripting the router's verdict rather than by building a
    pathological packing -- what is under test is the translation from
    `NetFailure` back to "which cut failed and why", which a caller several
    stages later has no other way to recover.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    seen: list[object] = []

    def stranded(canvas, nets, belt_id, belt_model, bounds, deadline=None, **kwargs):
        seen.extend(nets)
        failure = NetFailure(
            net_id=nets[0].net_id,
            kind=RouteFailureKind.SEALED_POCKET,
            wall=(),
            blocking_nets=(),
            expansions=0,
        )
        routed = tuple(net.net_id for net in nets[1:])
        return DetailedRouteResult(
            status=DetailedRouteStatus.STRANDED,
            routed=routed,
            failures=(failure,),
            iterations=1,
            expansions=0,
        )

    monkeypatch.setattr(compose, "_route_all", stranded)
    result = compose.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None)

    assert len(seen) == len(flows)
    assert result.routed == len(flows) - 1
    assert result.failures == (f"{flows[0].item}: block 0 -> block 1: SEALED_POCKET",)


def test_a_cut_the_router_never_reached_is_reported_under_its_status(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """A spent budget leaves nets neither routed nor failed; they are still cuts."""
    left, right, flows, spec, ramped = two_solved_blocks

    def out_of_budget(canvas, nets, belt_id, belt_model, bounds, deadline=None, **kwargs):
        return DetailedRouteResult(
            status=DetailedRouteStatus.BUDGET,
            routed=(),
            failures=(),
            iterations=0,
            expansions=0,
        )

    monkeypatch.setattr(compose, "_route_all", out_of_budget)
    result = compose.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None)

    assert result.routed == 0
    assert len(result.failures) == len(flows)
    assert all(f.endswith(": BUDGET") for f in result.failures)


def _chain_belts(cells: list[tuple[int, int]]) -> list[PlacedBuilding]:
    """A belt run through ``cells`` in path order, linked by ``output_obj``."""
    return [
        PlacedBuilding(
            item_id=catalog.BELT_IDS[0],
            model_index=catalog.building(catalog.BELT_IDS[0]).model_index,
            x=x,
            y=y,
            output_obj=None if i == len(cells) - 1 else i + 1,
        )
        for i, (x, y) in enumerate(cells)
    ]


#: East 3 on row 0, south 2, east 2, north 2 back to row 0, east 2 more.  Row 0
#: therefore holds TWO disjoint east-west segments of the SAME run -- x 0..2 and
#: x 4..6 -- which is the shape that raised `lane at 9865 is not one contiguous
#: row` out of `_port` on belt3.
_DOUBLE_BACK = [
    (0, 0),
    (1, 0),
    (2, 0),
    (2, 1),
    (2, 2),
    (3, 2),
    (4, 2),
    (4, 1),
    (4, 0),
    (5, 0),
    (6, 0),
]


def test_lane_takes_the_contiguous_segment_the_port_stands_in():
    buildings = _chain_belts(_DOUBLE_BACK)
    xs = lambda tiles: [buildings[i].x for i in tiles]  # noqa: E731

    # The last tile belongs to the segment the run came back to, not to the one
    # it started on -- even though both are at y == 0 and both are in this run.
    assert xs(compose._lane(buildings, 10)) == [4, 5, 6]
    # And the first tile belongs to the segment it starts.
    assert xs(compose._lane(buildings, 0)) == [0, 1, 2]
    # A tile in the middle of the far segment picks up the whole of it.
    assert xs(compose._lane(buildings, 9)) == [4, 5, 6]


def test_port_no_longer_asserts_on_a_run_that_doubles_back_to_its_row():
    """`_Port.at_tile` addresses taps as ``x0 + k``, so the span must be the tiles."""
    buildings = _chain_belts(_DOUBLE_BACK)
    for index in (0, 9, 10):
        port = compose._port(buildings, index, machines=1)
        assert port.x1 - port.x0 + 1 == len(port.tiles)
        assert port.belt == index
