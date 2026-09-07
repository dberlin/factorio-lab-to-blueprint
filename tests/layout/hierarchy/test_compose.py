import re
import time
from dataclasses import replace
from fractions import Fraction
from typing import NamedTuple

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout import junction, slots
from flab2bp.layout.base import Facing, PlacedBuilding, Placement
from flab2bp.layout.freeform import (
    PortAccessCorridor,
    PortAccessDemand,
    PortAccessEvidence,
    PortAccessKind,
    PortAccessReservation,
)
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


def test_pack_with_access_widens_the_gap_until_every_port_has_a_corridor(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """A packing whose ports have nowhere to run is not committed, it is widened.

    The fixture's own ports all obtain corridors at the narrowest gap, so the
    walled-in packing is scripted rather than built: the first reservation is
    the REAL one with one demand moved into `missing`, which is exactly the
    verdict a block packed too tightly against its neighbour produces. What is
    under test is that the composer answers that verdict by re-packing at the
    next rung instead of committing a canvas the router has to refuse on.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    seen: list[int] = []
    real = compose._reserve_port_access

    def scripted(canvas, demands, **kw):
        seen.append(kw["bounds"][2] - kw["bounds"][0])
        reservation = real(canvas, demands, **kw)
        if len(seen) == 1:  # first gap: pretend one port is walled in
            return replace(reservation, missing=demands[:1], assigned=reservation.assigned[1:])
        return reservation

    monkeypatch.setattr(compose, "_reserve_port_access", scripted)
    packed = compose.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8
    )

    assert packed.gap == compose.GAP_LADDER[1]
    assert packed.reservation.complete
    # The committed reservation is STAKED ON the committed canvas -- that is
    # `PackedCanvas`'s own contract and the reason `compose` routes on this
    # canvas rather than reserving again.  A refactor that detached the
    # verdict from the canvas it was staked on would leave this empty.
    assert packed.canvas.port_corridors, "the committed reservation must be staked on the canvas"


def test_pack_with_access_passes_the_outer_ring_only_when_a_demand_can_use_it(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """The rim goes with the question exactly when a demand could be probed at it.

    `_reserve_port_access` runs its reachability probe -- "does this corridor
    LEAD anywhere?" -- only for demands whose kind `reaches_boundary`, and
    every demand `compose` builds out of its nets is an `INTERNAL_DEPARTURE`
    or an `INTERNAL_ARRIVAL`, neither of which is.  Passing the rim anyway
    would be pure cost on a clock the gate shows binding: a `_Grid` over the
    whole route box per ladder rung, and a validate callback re-run on every
    candidate assignment, both for a probe that never runs.  So compose
    withholds it -- and hands over the rim of `canvas.limit`, unchanged, the
    moment a demand appears that CAN be probed against it (the v2 gate's §6
    lever 1, "give the composer real boundary ports").
    """
    left, right, flows, spec, ramped = two_solved_blocks
    captured: list[object] = []
    limits: list[object] = []
    real = compose._reserve_port_access

    def spy(canvas, demands, **kw):
        captured.append(kw["boundary"])
        limits.append(canvas.limit)
        return real(canvas, demands, **kw)

    monkeypatch.setattr(compose, "_reserve_port_access", spy)
    compose.pack_with_access([left, right], flows, spec, ramped=ramped, deadline=None, margin=8)
    assert captured and all(boundary is None for boundary in captured), (
        "no demand compose builds reaches the boundary, so the rim is pure cost"
    )

    real_inventory = compose._port_access_inventory

    def with_a_boundary_demand(nets, **kw):
        inventory = real_inventory(nets, **kw)
        head, *rest = inventory.demands
        return replace(
            inventory,
            demands=(replace(head, kind=PortAccessKind.BOUNDARY_ARRIVAL), *rest),
        )

    captured.clear()
    limits.clear()
    monkeypatch.setattr(compose, "_port_access_inventory", with_a_boundary_demand)
    compose.pack_with_access([left, right], flows, spec, ramped=ramped, deadline=None, margin=8)

    boundary = captured[0]
    assert boundary is not None, "a boundary-reaching demand must be given the rim to reach"
    ring = set(boundary)
    limit = limits[0]
    assert isinstance(limit, tuple)
    x0, y0, x1, y1 = limit
    assert (x0, y0, 0) in ring and (x1, y1, 0) in ring
    assert all(x in (x0, x1) or y in (y0, y1) for x, y, _ in ring)


def test_the_gap_ladder_leaves_the_router_a_live_clock(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """The rungs are speculative; the wall belongs to the stage that lays belts.

    Every rung here comes back incomplete, which is the case the ladder exists
    for and the worst case for its cost: a ladder handed the whole clock walks
    all of `GAP_LADDER`, paying a pack, a canvas and a reservation each time,
    and then leaves `_route_all` a deadline that has already passed -- refusing
    under BUDGET on cuts the FIRST rung would have wired.

    The reservation is the real one; only its own clock is neutralised (it is
    called with `deadline=None`), so what is measured is the LADDER's bound and
    not the reservation's own deadline check.

    THE LADDER'S CLOCK IS A FAKE ONE, advanced by a fixed burn per rung instead
    of slept through.  What is under test is the ARITHMETIC of the bound --
    when the ladder stops and how much of the window it leaves behind -- and a
    real sleep on a box that is never idle would make a scheduling hiccup, not
    a broken bound, the thing this test reports.  The reservation itself still
    runs for real on the real clock; only `compose`'s own reading of the time
    is scripted.  The assertion is relative to `LADDER_WALL_SHARE` for the same
    reason: it is the guarantee, not a number that happens to hold today.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    real = compose._reserve_port_access
    rungs: list[int] = []
    window_s = 2.0
    burn_s = 0.2

    class _LadderClock:
        """`compose`'s view of the time, advanced only by a rung's own cost."""

        now = 0.0

        def monotonic(self) -> float:
            return self.now

    clock = _LadderClock()

    def slow_and_incomplete(canvas, demands, **kw):
        rungs.append(len(rungs))
        reservation = real(canvas, demands, **{**kw, "deadline": None, "cancelled": None})
        clock.now += burn_s
        return replace(reservation, missing=demands[:1], assigned=reservation.assigned[1:])

    monkeypatch.setattr(compose, "time", clock)
    monkeypatch.setattr(compose, "_reserve_port_access", slow_and_incomplete)
    deadline = clock.monotonic() + window_s
    packed = compose.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=deadline, margin=8
    )
    left_over = deadline - clock.monotonic()

    assert not packed.reservation.complete, "the scripted rungs must all come back incomplete"
    assert len(rungs) < len(compose.GAP_LADDER), "the ladder must stop before spending every rung"
    # Everything but the ladder's own share, less the one rung it may overshoot
    # by: a rung is only checked BEFORE it runs, so the one that crosses the
    # share still finishes.
    assert left_over >= window_s * (1.0 - compose.LADDER_WALL_SHARE) - burn_s, (
        "the router must be handed the wall the ladder was never allowed to spend"
    )


def test_pack_with_access_starts_the_ladder_at_the_gap_it_was_given(
    two_solved_blocks: TwoSolvedBlocks,
):
    """``gap`` is the ladder's FLOOR: rungs below it are never packed.

    Without the floor -- with the ladder simply walking `GAP_LADDER` -- this
    fixture's ports obtain corridors at rung 0 and the committed gap would be 2.
    A caller that knows two blocks cannot be laid closer than 8 has to be
    believed.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    packed = compose.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8, gap=8
    )
    assert packed.gap >= 8


def test_a_floor_above_every_rung_is_itself_the_only_rung(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """A ladder must always try once, so an unreachable floor becomes the rung."""
    left, right, flows, spec, ramped = two_solved_blocks
    real = compose._reserve_port_access
    rungs: list[int] = []

    def counted(canvas, demands, **kw):
        rungs.append(len(rungs))
        return real(canvas, demands, **kw)

    monkeypatch.setattr(compose, "_reserve_port_access", counted)
    floor = max(compose.GAP_LADDER) + 4
    packed = compose.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8, gap=floor
    )

    assert packed.gap == floor
    assert len(rungs) == 1


def test_trunk_goals_point_each_lane_head_at_its_partners_doorstep(
    two_solved_blocks: TwoSolvedBlocks,
):
    """A cut lane's goal is the far end of its own trunk, never the rim.

    This is also the standing proof that every goal cell is inside the `bounds`
    the reservation is given: `_free_doorstep` admits a neighbour only through
    `_Canvas.free`, which refuses anything outside `canvas.limit` -- and
    `pack_with_access` passes that same `canvas.limit` as `bounds`.  A goal
    outside `bounds` would be silently unreachable in `_astar` (only START
    cells are exempt from the box), turning a geometry question into a false
    `missing`.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    packing = compose._pack_at([left, right], flows, spec, gap=2, ramped=ramped, margin=8)
    demands = compose._port_access_inventory(packing.nets).demands
    goals = compose._trunk_goals(packing, demands)
    assert goals, "every cut lane must raise a goal"
    net = packing.nets[0]
    src_cell = (net.src.x, net.src.y, net.src.z)
    dst_cell = (net.dst.x, net.dst.y, net.dst.z)
    departure = next(d for d in goals if d.cell == src_cell)
    # The departure's goal is the ARRIVAL's free neighbours, not the rim -- and
    # a lane head that is the end of SEVERAL nets is aimed at the union of its
    # partners' doorsteps, which is the "at least one of them" the docstring
    # calls deliberately weaker than routing.
    partners: set[tuple[int, int, int]] = set()
    for other in packing.nets:
        if other.prelinked or other.src is None:
            continue
        ends = ((other.src.x, other.src.y, other.src.z), (other.dst.x, other.dst.y, other.dst.z))
        if src_cell in ends:
            partners.update(ends)
    partners.discard(src_cell)
    assert goals[departure] <= {
        (px + dx, py + dy, pz) for px, py, pz in partners for dx, dy in compose._NEIGHBOURS
    }, "a goal cell that touches no partner lane head is the rim creeping back in"
    assert goals[departure] >= {
        cell
        for dx, dy in compose._NEIGHBOURS
        for cell in ((dst_cell[0] + dx, dst_cell[1] + dy, dst_cell[2]),)
        if packing.canvas.free(cell)
    }, "this net's own far end must be among the doorsteps its departure is aimed at"
    assert all(packing.canvas.free(cell) for cell in goals[departure])
    x0, y0, x1, y1 = packing.canvas.limit
    assert all(x0 <= x <= x1 and y0 <= y <= y1 for cells in goals.values() for x, y, _z in cells), (
        "a goal outside `bounds` is unreachable in `_astar` and would refuse for the wrong reason"
    )


def _partners_of(packing, cell: tuple[int, int, int]) -> set[tuple[int, int, int]]:
    """Every lane head at the OTHER end of a net ``cell`` is an end of."""
    partners: set[tuple[int, int, int]] = set()
    for net in packing.nets:
        if net.prelinked or net.src is None:
            continue
        ends = ((net.src.x, net.src.y, net.src.z), (net.dst.x, net.dst.y, net.dst.z))
        if cell in ends:
            partners.update(ends)
    partners.discard(cell)
    return partners


def test_a_lane_head_whose_every_partner_is_walled_in_raises_no_goal(
    two_solved_blocks: TwoSolvedBlocks,
):
    """REAL GEOMETRY, not a scripted verdict: the omission half of the payload.

    A demand whose every partner is sealed raises NO goal rather than an empty
    one -- an empty goal set is a search that can never settle, and would
    convict this demand for its PARTNER's pocket.  The router names that lane
    itself, with the class that actually stopped it.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    packing = compose._pack_at([left, right], flows, spec, gap=2, ramped=ramped, margin=8)
    demands = compose._port_access_inventory(packing.nets).demands
    head = (packing.nets[0].src.x, packing.nets[0].src.y, packing.nets[0].src.z)
    assert any(d.cell == head for d in compose._trunk_goals(packing, demands)), (
        "the head must raise a goal before anything is walled in"
    )

    # Wall in every partner's doorstep, so no partner of `head` has a free cell
    # a belt could stand on.  `keep_out` is (x, y) and so denies every altitude:
    # a ramp up to a walled cell is not an escape either.
    partners = _partners_of(packing, head)
    assert partners, "the fixture's first net must have a partner to wall in"
    for px, py, _pz in partners:
        for dx, dy in compose._NEIGHBOURS:
            packing.canvas.keep_out.add((px + dx, py + dy))

    goals = compose._trunk_goals(packing, demands)
    assert all(demand.cell != head for demand in goals), (
        "a demand with no reachable partner doorstep must be OMITTED, not given an empty goal"
    )
    assert goals, "the other lane heads must keep their goals"


def test_a_sealed_lane_head_is_put_in_missing_by_the_trunk_probe(
    two_solved_blocks: TwoSolvedBlocks,
):
    """REAL GEOMETRY: the payload of the whole lever, on the real A* and matcher.

    Nothing is monkeypatched here.  A ring of walls at Chebyshev distance 2
    around one lane head leaves its own four neighbours -- and therefore its
    LOCAL options -- untouched, which is exactly the case v2's local-only
    oracle cannot see: it admits every one of those options unprobed and
    reports `missing` empty, while the router then has nowhere to run.  The
    trunk goals ask the router's question instead, and the pocket answers it.

    The `assigned` assertion is load-bearing: a verdict that emptied the whole
    assignment would be discarded by `pack_with_access`'s R7 degradation, so a
    test that tripped it would prove nothing about the oracle.  That is why the
    packing is a SECOND, independent copy of the fixture's pair alongside the
    first: the chain has one cut, so sealing a head of a lone pair seals every
    demand there is and the verdict could not be a graded one.  A gap of 8 puts
    the walls clear of the partner block.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    untouched = [
        replace(
            flow,
            src=replace(flow.src, block=flow.src.block + 2),
            dst=replace(flow.dst, block=flow.dst.block + 2),
        )
        for flow in flows
    ]
    packing = compose._pack_at(
        [left, right, left, right], [*flows, *untouched], spec, gap=8, ramped=ramped, margin=8
    )
    canvas = packing.canvas
    demands = compose._port_access_inventory(packing.nets).demands
    bounds = canvas.limit
    head = (packing.nets[0].src.x, packing.nets[0].src.y, packing.nets[0].src.z)

    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            if max(abs(dx), abs(dy)) == 2:
                canvas.keep_out.add((head[0] + dx, head[1] + dy))

    goals = compose._trunk_goals(packing, demands)
    assert any(d.cell == head for d in goals), "the partner is untouched, so the goal survives"

    # v2's oracle: the local options are all still free, so it admits the head.
    # `_reserve_port_access` clears `reserved`/`port_corridors` on entry, so the
    # two calls below do not see each other's stakes.
    local_only = compose._reserve_port_access(canvas, demands, boundary=None, bounds=bounds)
    assert all(demand.cell != head for demand in local_only.missing), (
        "the wall must not starve the head LOCALLY -- otherwise this proves nothing new"
    )

    probed = compose._reserve_port_access(
        canvas, demands, boundary=None, bounds=bounds, goals=goals
    )
    assert any(demand.cell == head for demand in probed.missing), (
        "the trunk probe must name the head the router cannot run a corridor out of"
    )
    assert probed.assigned, "a graded rejection keeps assigning the demands it did not reject"
    assert not probed.complete


def test_pack_with_access_hands_the_reservation_the_trunk_goals(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """The oracle is asked the router's question, not the local-only one."""
    left, right, flows, spec, ramped = two_solved_blocks
    captured: dict[str, object] = {}
    real = compose._reserve_port_access

    def spy(canvas, demands, **kw):
        captured.setdefault("goals", kw.get("goals"))
        return real(canvas, demands, **kw)

    monkeypatch.setattr(compose, "_reserve_port_access", spy)
    compose.pack_with_access([left, right], flows, spec, ramped=ramped, deadline=None, margin=8)
    assert captured["goals"], "the reservation was still asked the local-only question"


def test_a_walled_in_trunk_rejects_the_narrow_rung(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """The upper rungs must become reachable: today rung 0 always commits."""
    left, right, flows, spec, ramped = two_solved_blocks
    real = compose._reserve_port_access
    # The ladder walks narrowest-first, so the FIRST call's box is the
    # narrowest packing's; every later rung is strictly wider.
    narrowest: dict[str, int] = {}

    def scripted(canvas, demands, **kw):
        reservation = real(canvas, demands, **kw)
        width = kw["bounds"][2] - kw["bounds"][0]
        narrowest.setdefault("width", width)
        if width == narrowest["width"]:  # the narrowest packing
            return replace(reservation, missing=demands[:1], assigned=reservation.assigned[1:])
        return reservation

    monkeypatch.setattr(compose, "_reserve_port_access", scripted)
    packed = compose.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8
    )
    assert packed.gap > compose.GAP_LADDER[0]
    assert packed.reservation.complete


def test_rung_zero_falls_back_to_the_local_oracle_on_its_own_deadline(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """A slow trunk probe must not cost the router its wall."""
    left, right, flows, spec, ramped = two_solved_blocks
    calls: list[object] = []
    real = compose._reserve_port_access

    def slow_first(canvas, demands, **kw):
        calls.append(kw.get("goals"))
        if len(calls) == 1:
            raise compose._PreparationDeadline
        return real(canvas, demands, **kw)

    monkeypatch.setattr(compose, "_reserve_port_access", slow_first)
    packed = compose.pack_with_access(
        [left, right],
        flows,
        spec,
        ramped=ramped,
        deadline=time.monotonic() + 30.0,
        margin=8,
    )
    assert len(calls) == 2
    assert calls[0] is not None and calls[1] is None, "the retry must drop the goals"
    assert packed.gap == compose.GAP_LADDER[0]
    # The deadline and the unusable answer take the SAME fallback, so they are
    # counted the same way -- one behaviour to reason about, not two.
    assert packed.degraded == 1


def test_an_empty_assignment_is_re_asked_as_the_local_only_question(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """An assignment of NOTHING is an unusable answer, not a geometric verdict.

    This is the WHOLESALE give-up: `_match_access_corridors` returns `{}`
    wholesale (rather than committing whatever partial its survey left
    unconvicted) either directly -- an infeasible initial rank solve, or no
    demand having a single free option while demands were raised -- or via
    its `surrender()` fallback, which reaching is NECESSARY but not
    SUFFICIENT for `{}`: `surrender()` hands back a non-empty partial unless
    no partial was ever recorded, no `survey` callback was passed at all, its
    survey is cut short by its own deadline, or the survey convicts every
    demand the partial held.  Every one of those routes is `converged=False`.
    So the mock scripts that too, or `pack_with_access`'s new
    `goal_driven.converged` trigger would commit this empty answer directly
    instead of falling back.
    An empty reservation stakes NO corridors -- so acting on one leaves the
    router worse off than v2's local-only oracle.  The belt3 measurement had
    exactly that: all 102 demands discarded on a canvas the router still
    wired 65 of 89 cuts on.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    real = compose._reserve_port_access
    asked: list[object] = []

    def empty_when_asked_about_trunks(canvas, demands, **kw):
        asked.append(kw.get("goals"))
        reservation = real(canvas, demands, **kw)
        if kw.get("goals") is not None:
            assert demands, "the fixture must raise demands for this to be the unusable case"
            return replace(reservation, assigned=(), missing=demands, converged=False)
        return reservation

    monkeypatch.setattr(compose, "_reserve_port_access", empty_when_asked_about_trunks)
    packed = compose.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8
    )

    assert asked[0] is not None and asked[1] is None, "the retry must drop the goals"
    # The LOCAL-ONLY answer is the one the rung was judged by, and it is a real
    # one: it assigns corridors, so the router is handed v2's canvas.
    assert packed.reservation.assigned
    assert packed.reservation.complete
    assert packed.gap == compose.GAP_LADDER[0]
    assert packed.degraded == 1


def _reservation(
    demands: list[PortAccessDemand], assigned_count: int, *, converged: bool
) -> PortAccessReservation:
    """A `PortAccessReservation` over the first `assigned_count` demands."""
    served = demands[:assigned_count]
    return PortAccessReservation(
        assigned=tuple(
            (demand, PortAccessCorridor((0, 0, 0), (0, 1, 0), demand.kind)) for demand in served
        ),
        missing=tuple(demands[assigned_count:]),
        evidence=(),
        converged=converged,
    )


def test_a_committed_partial_is_counted_as_partial_and_as_degraded(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
) -> None:
    # THE R7 RESIDUAL, PINNED. A one-corridor partial must never reach the
    # stats line with reservation_degraded=0, because that pair -- degraded 0,
    # missing 0 -- is the only way a reader can trust `missing`.
    left, right, flows, spec, ramped = two_solved_blocks

    def fake_reserve(canvas, demands, **kwargs):
        if kwargs.get("goals"):
            return _reservation(list(demands), 1, converged=False)
        raise AssertionError("the local-only oracle must not be re-asked for a partial")

    monkeypatch.setattr(compose, "_reserve_port_access", fake_reserve)
    packed = compose.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8
    )

    assert len(packed.reservation.assigned) == 1
    assert packed.partial >= 1
    assert packed.degraded >= 1
    # The docstring's own contract on `PackedCanvas.partial`: every partial is
    # also degraded, so this can never invert.
    assert packed.partial <= packed.degraded


def test_a_wholesale_empty_answer_still_falls_back_to_the_local_only_oracle(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
) -> None:
    left, right, flows, spec, ramped = two_solved_blocks
    asked_local = 0

    def fake_reserve(canvas, demands, **kwargs):
        nonlocal asked_local
        if kwargs.get("goals"):
            return _reservation(list(demands), 0, converged=False)
        asked_local += 1
        return _reservation(list(demands), len(list(demands)), converged=True)

    monkeypatch.setattr(compose, "_reserve_port_access", fake_reserve)
    packed = compose.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8
    )

    assert asked_local >= 1
    assert packed.degraded >= 1
    assert packed.partial == 0


def test_a_converged_answer_is_neither_partial_nor_degraded(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
) -> None:
    left, right, flows, spec, ramped = two_solved_blocks

    def fake_reserve(canvas, demands, **kwargs):
        assert kwargs.get("goals"), "a converged trunk answer must not be re-asked"
        return _reservation(list(demands), len(list(demands)), converged=True)

    monkeypatch.setattr(compose, "_reserve_port_access", fake_reserve)
    packed = compose.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8
    )

    assert packed.degraded == 0
    assert packed.partial == 0


def test_a_converged_but_empty_answer_does_not_bypass_the_local_only_oracle(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The restored structural guard: `converged=True` alone is not enough.

    `_CorridorMatch` only reports `converged=True` with an empty assignment
    for an EMPTY question (`not demands`) -- never a non-empty one. A
    `converged=True, assigned=()` reservation while demands were raised is
    therefore not a real answer, and the first branch's guard
    (`goal_driven.assigned or not demands`) exists to stop it being committed
    unchecked: without it, `reservation_degraded == 0` would sit beside
    `missing == every demand`, exactly the failure mode this task exists to
    close.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    asked_local = 0

    def fake_reserve(canvas, demands, **kwargs):
        nonlocal asked_local
        if kwargs.get("goals"):
            return _reservation(list(demands), 0, converged=True)
        asked_local += 1
        return _reservation(list(demands), len(list(demands)), converged=True)

    monkeypatch.setattr(compose, "_reserve_port_access", fake_reserve)
    packed = compose.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8
    )

    assert asked_local >= 1, "the empty-but-converged answer must not be committed unchecked"
    assert packed.degraded >= 1
    assert packed.partial == 0


def test_compose_reports_the_rung_and_the_reservation_it_committed(
    two_solved_blocks: TwoSolvedBlocks,
):
    left, right, flows, spec, ramped = two_solved_blocks
    result = compose.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None)
    assert result.gap in compose.GAP_LADDER
    assert result.port_demands > 0
    assert result.reservation_missing == 0
    # `reservation_missing == 0` only reads as "every port is satisfiable"
    # while nothing was degraded, which is what makes the pair worth reporting.
    assert result.reservation_degraded == 0
    assert result.failures == () and result.routed == len(flows)


def test_compose_still_routes_both_cuts_on_the_chain(two_solved_blocks: TwoSolvedBlocks):
    """The ladder, floored at today's gap, does not change today's outcome.

    `compose` no longer packs at the gap it was handed -- it hands that gap to
    :func:`pack_with_access` as the ladder's FLOOR and commits whichever rung
    first gives every port a corridor. This is the regression guard on that
    change: the chain composed at `gap=2` before, and must still.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    result = compose.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None)
    assert result.failures == ()
    assert result.routed == len(flows)


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


def test_composition_reports_a_tile_it_could_not_power_as_a_named_cut(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compose, "plan_power_infill", lambda canvas, **kwargs: ([], ((63, 3),)))

    left, right, flows, spec, ramped = two_solved_blocks
    result = compose.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None)

    assert result.power_uncovered == 1
    assert any("power.coverage" in failure and "(63,3)" in failure for failure in result.failures)


def test_compose_reports_an_unwired_cut_instead_of_handing_it_back(
    two_solved_blocks: TwoSolvedBlocks,
):
    """A real verdict, not a mock: the deadline is already spent.

    Whichever stage reads the clock first refuses -- the port reservation, which
    is entered with the same deadline and raises `_PreparationDeadline` on an
    expired one, before `_route_all` (which checks its own deadline between
    rounds AND between nets and never commits the live paths once it has
    expired). Either way every cut comes back unwired. What is under test here
    is that they come back NAMED -- an unwired entry lane the composer swallowed
    is a block that starves, convicted many stages later with no way back to the
    cause. That the reservation is the stage that stops is pinned separately by
    `test_an_expired_deadline_stops_the_reservation_without_raising`.
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


def test_an_expired_deadline_stops_the_reservation_without_raising(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """The reservation runs under the composition's clock, and refuses in it.

    `_reserve_port_access` raises `_PreparationDeadline` when it is entered past
    its deadline -- `_prepare_routing_problem` lets that unwind to whoever owns
    the budget, but `compose` promises a `ComposeResult`. What is under test is
    that the deadline REACHES the reservation (the router is never even called)
    and that the cut lines come back in the ordinary shape.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    routed_calls: list[object] = []
    monkeypatch.setattr(
        compose, "_route_all", lambda *a, **k: routed_calls.append(a) or pytest.fail("routed")
    )

    result = compose.compose(
        [left, right], flows, spec, gap=2, ramped=ramped, deadline=time.monotonic() - 1.0
    )

    assert routed_calls == [], "an expired reservation must not go on to route"
    assert result.routed == 0
    assert len(result.failures) == len(flows)
    for line in result.failures:
        assert re.fullmatch(r"\S+: block \d+ -> block \d+: BUDGET", line), line


def test_a_missing_port_corridor_is_named_by_item_and_block(
    two_solved_blocks: TwoSolvedBlocks, monkeypatch: pytest.MonkeyPatch
):
    """The reservation's verdict is REPORTED, not discarded.

    The fixture's ports all obtain corridors, so the reporting path is reached by
    scripting the matcher's verdict. A port with no corridor is a lane head no
    net can start from; discarding the verdict left the router to fail those
    nets later with `DYNAMIC_ACCESS` and no way back to the cause -- which is
    what `_prepare_routing_problem` builds `StrandedPort` to avoid.
    """
    left, right, flows, spec, ramped = two_solved_blocks
    real_reserve = compose._reserve_port_access
    seen: list[PortAccessReservation] = []

    def one_missing(canvas, demands, **kwargs):
        reservation = real_reserve(canvas, demands, **kwargs)
        stranded = demands[0]
        cut = PortAccessReservation(
            assigned=reservation.assigned,
            missing=(stranded,),
            evidence=(
                PortAccessEvidence(
                    demand=stranded,
                    held=1,
                    wanted=2,
                    local_options=1,
                    reachable_options=1,
                    exhaustive=True,
                ),
            ),
        )
        seen.append(cut)
        return cut

    monkeypatch.setattr(compose, "_reserve_port_access", one_missing)
    result = compose.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None)

    assert seen, "the composer must call the reservation"
    stranded = seen[0].missing[0]
    block = compose._block_of(result.blocks, stranded.belt)
    line = (
        f"{stranded.item}: block {block} lane head {stranded.belt}: "
        "no port access corridor (held=1 wants=2 options=1)"
    )
    assert line in result.failures


def test_block_of_names_the_block_a_composed_index_belongs_to(
    two_solved_blocks: TwoSolvedBlocks,
):
    """Every index in a block's own range answers with that block."""
    left, right, flows, spec, ramped = two_solved_blocks
    result = compose.compose([left, right], flows, spec, gap=2, ramped=ramped, deadline=None)
    for block in result.blocks:
        stop = block.base + len(block.placement.buildings)
        assert {compose._block_of(result.blocks, i) for i in range(block.base, stop)} == {
            block.index
        }


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


def test_the_doorstep_neighbourhood_is_the_one_reserve_port_access_enumerates():
    """`_NEIGHBOURS` duplicates `freeform._STEPS` by value, and unenforced.

    `_free_doorstep`'s docstring claims its output "is exactly the
    `access_cells` set `_reserve_port_access` enumerates" -- true only while
    the two neighbourhoods agree, which nothing else in either module checks.
    """
    from flab2bp.layout.freeform import _STEPS

    assert set(compose._NEIGHBOURS) == set(_STEPS)


def test_port_no_longer_asserts_on_a_run_that_doubles_back_to_its_row():
    """`_Port.at_tile` addresses taps as ``x0 + k``, so the span must be the tiles."""
    buildings = _chain_belts(_DOUBLE_BACK)
    for index in (0, 9, 10):
        port = compose._port(buildings, index, machines=1)
        assert port.x1 - port.x0 + 1 == len(port.tiles)
        assert port.belt == index
