import pytest

from flab2bp.layout.base import Placement
from flab2bp.layout.hierarchy import compose
from flab2bp.layout.hierarchy.contracts import LaneFlow
from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    NetFailure,
    RouteFailureKind,
)
from flab2bp.spec import BuildSpec

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


def test_compose_reports_an_unroutable_cut_instead_of_handing_it_back(
    two_solved_blocks: TwoSolvedBlocks,
):
    left, right, flows, spec, ramped = two_solved_blocks
    walled = compose.compose(
        [left, right],
        flows,
        spec,
        gap=2,
        ramped=ramped,
        deadline=None,
        _limit_margin=0,  # no room outside the packed boxes
    )
    assert walled.failures or walled.routed == len(flows)
    # Either the router still finds a path inside the gap, or it names the
    # failure; never silence.
    assert not any("external_input" in f for f in walled.failures)


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
