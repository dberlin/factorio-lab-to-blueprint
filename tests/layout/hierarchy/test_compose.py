import re
import time
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout import slots
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
from tests.layout.hierarchy.conftest import chain_spec

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


def _coater_canvas() -> tuple[list[PlacedBuilding], int, int, tuple[int, int, int]]:
    """A hand-built composed block: a lane, a Coater on it, a sorter, a machine."""
    spec = chain_spec()
    belt_id = catalog.get_item_id(spec.belt_item_id) or 2001
    belt_model = catalog.building(belt_id).model_index
    coater = PlacedBuilding(
        item_id=catalog.SPRAY_COATER_ID,
        model_index=catalog.building(catalog.SPRAY_COATER_ID).model_index,
        x=3,
        y=0,
        z=Fraction(0),
        width=1,
        height=1,
        yaw=Facing.EAST.value,
    )
    drop = slots.addon_supply_cell(
        catalog.SPRAY_COATER_ID, x=coater.x, y=coater.y, z=coater.z, yaw=coater.yaw, area=1
    )
    approach = (2 * drop[0] - coater.x, 2 * drop[1] - coater.y)
    # The host lane on the ground, plus the Coater's supply pair at the drop's
    # own altitude -- which is a level up, not a tile across.
    cells = [(x, 0, Fraction(0)) for x in range(7)] + [
        (drop[0], drop[1], Fraction(drop[2])),
        (approach[0], approach[1], Fraction(drop[2])),
    ]
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
        for x, y, z in cells
    ]
    sorter_index = len(buildings)
    buildings.append(
        PlacedBuilding(
            item_id=catalog.SORTER_TIERS[0],
            model_index=catalog.building(catalog.SORTER_TIERS[0]).model_index,
            x=2,
            y=4,
            width=1,
            height=1,
        )
    )
    machine_id = catalog.get_item_id("arc-smelter")
    assert machine_id is not None
    machine = catalog.building(machine_id)
    machine_index = len(buildings)
    buildings.append(
        PlacedBuilding(
            item_id=machine_id,
            model_index=machine.model_index,
            x=8,
            y=6,
            width=machine.width,
            height=machine.height,
            recipe_id=1,
        )
    )
    buildings.append(coater)
    return buildings, sorter_index, machine_index, drop


def test_canvas_for_registers_each_building_kind_the_way_freeform_does():
    """Kind by kind, and the Coater's belt ban is the one the game enforces.

    A composed canvas that marks a sorter solid costs the router paths the game
    allows, and one that never prices a Coater's collider lets it lay a level-1
    belt beside the Coater that the game refuses on paste.
    """
    buildings, sorter_index, machine_index, drop = _coater_canvas()
    canvas = compose.canvas_for(chain_spec(), buildings, ramped=False, margin=4)

    # Index order is the composed list's own: every `_Port` indexes into it.
    assert canvas.buildings == buildings

    sorter = buildings[sorter_index]
    assert (sorter.x, sorter.y) not in canvas.solid
    assert not any(key[:2] == (sorter.x, sorter.y) for key in canvas.blocked)

    machine = buildings[machine_index]
    assert (machine.x, machine.y) in canvas.solid
    assert any(key[:2] == (machine.x, machine.y) for key in canvas.blocked)

    coater = buildings[-1]
    assert canvas.belt_ban, "a composed Coater must price its own collider"
    banned = set(canvas.belt_ban)
    assert any(abs(x - coater.x) <= 2 and abs(y - coater.y) <= 2 for x, y in banned)
    assert all(levels and min(levels) >= 1 for levels in canvas.belt_ban.values())
    # The drop is a required positional addon connection and is exempt.
    assert (drop[0], drop[1]) not in canvas.belt_ban


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
