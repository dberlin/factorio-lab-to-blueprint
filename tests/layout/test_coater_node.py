"""``FLAB2BP_COATER_NODE``: each arm's emitted geometry, pinned.

Two arms, compared on the same tree rather than argued about.  The measured
evidence that chose between them is
``docs/superpowers/evidence/2026-09-07-exp-coater-node/README.md``.

``placed``
    The default and the production model.  The Spray Coater as a real node: a
    five-tile belt run with the addon on its third tile, its in-port and
    out-port off the body, sited by a post-pack free-ground pass beside the
    consumer lane head.  The consumer's lane goes back to an ordinary
    ``WEST_CHANNEL`` lane with no coater on it at all.

``off``
    Master's behaviour before 2026-09-07, retained for one release as the A/B
    control.  The addon rides the interior of the consumer strip's own
    ``_COATER_WEST_CHANNEL`` and the first seat candidate puts the 3x1 body
    over the lane HEAD -- the one cell of the lane a router path can reach, so
    the cell every many-to-one merge lands on.  That is the reported defect.

Every test here sets the environment variable rather than a parameter,
because that is how the arm is selected in production code and a test that
poked a module global would pass while the real switch did nothing.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction as F

import pytest

from flab2bp.dsp import catalog, colliders
from flab2bp.dsp.records import is_belt
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.layout import finalize, routing_domain, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import Facing, PlacedBuilding, Placement
from flab2bp.layout.coater_mode import CoaterMode, coater_mode
from flab2bp.layout.freeform import _COATER_WEST_CHANNEL, FreeformLayout, plan_strips
from flab2bp.layout.routing_domain import WEST_CHANNEL, _Canvas, _Port
from flab2bp.layout.strip_variants import CargoDomain
from flab2bp.spec import BuildSpec, MachineGroup, ProliferatorMode

_BELT_RULES = belt_rules_for_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*60&v=11")


PROLIFERATED_BUDGET_S = 4.0


def _spec() -> BuildSpec:
    """The smallest spec that asks for one sprayed lane.

    Four smelters feeding four proliferated gear assemblers: one sprayed input
    lane, one Spray Coater, and ``belt_required_edges`` forbidding the direct
    insert that would otherwise delete the lane the coater has to ride.
    """
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=4,
                proliferator_mode=ProliferatorMode.NONE,
                inputs_per_machine={"iron-ore": F(1)},
                outputs_per_machine={"iron-ingot": F(1)},
            ),
            MachineGroup(
                recipe_id="gear",
                machine_item_id="assembling-machine-2",
                count=4,
                proliferator_mode=ProliferatorMode.PRODUCTS,
                inputs_per_machine={"iron-ingot": F(1)},
                outputs_per_machine={"gear": F(1)},
            ),
        ),
        external_inputs={"iron-ore": F(4), "proliferator-3": F(1) / 2},
        outputs={"gear": F(4)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="proliferated",
        belt_required_edges=frozenset({("iron-ingot", "gear")}),
        spray_lanes={"iron-ingot": False},
    )


def _arm(monkeypatch: pytest.MonkeyPatch, arm: str) -> None:
    monkeypatch.setenv("FLAB2BP_COATER_NODE", arm)
    assert coater_mode() is CoaterMode(arm)


def _lane_port(canvas: _Canvas, tiles: int, *, item: str = "iron-ingot") -> _Port:
    indices = [
        canvas.add(
            PlacedBuilding(
                item_id=catalog.item_id("conveyor-belt-2"),
                model_index=catalog.building(catalog.item_id("conveyor-belt-2")).model_index,
                x=x,
                y=0,
                width=1,
                height=1,
                yaw=Facing.EAST.value,
                carries_item=item,
            )
        )
        for x in range(tiles)
    ]
    return _Port(
        indices[0],
        0,
        0,
        0,
        tiles - 1,
        tuple(indices),
        1,
        0,
        cargo_domain=CargoDomain.REQUIRES_SPRAY,
    )


def test_adjacent_coaters_can_feed_from_opposite_transverse_sides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The captured sequence pair is diagonally offset by (1, 1) before
    # frame rotation: the second preferred approach sits over the first body.
    _arm(monkeypatch, "off")
    spec = _spec()
    strip = dataclasses.replace(
        next(
            strip for strip in plan_strips(spec) if strip.cargo_domain is CargoDomain.REQUIRES_SPRAY
        ),
        west_channel=2,
    )
    canvas = _Canvas(limit=(-4, -4, 8, 8))
    belt_id = catalog.item_id("conveyor-belt-2")
    belt_model = catalog.building(belt_id).model_index
    ports: list[dict[str, _Port]] = []
    for y in (0, 1):
        indices: list[int] = []
        for x in range(4):
            index = len(canvas.buildings)
            indices.append(
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=x + y,
                        y=y,
                        width=1,
                        height=1,
                        output_obj=index + 1 if x < 3 else None,
                        carries_item="iron-ingot",
                    )
                )
            )
        ports.append(
            {
                "iron-ingot": _Port(
                    indices[0],
                    y,
                    y,
                    y,
                    3 + y,
                    tuple(indices),
                    1,
                    0,
                    cargo_domain=CargoDomain.REQUIRES_SPRAY,
                )
            }
        )
    supplies = routing_domain._place_coaters(
        canvas,
        spec,
        [strip, strip],
        ports,
        belt_id,
        belt_model,
        policy=BandPolicy("160"),
    )
    assert len(supplies) == 2
    first, second = supplies
    assert canvas.buildings[first.approach_belt].y < first.y
    assert canvas.buildings[second.approach_belt].y > second.y
    report = validate.validate(
        Placement(buildings=tuple(canvas.buildings)),
        only={
            "geom.collide",
            "game.belt_crossing",
            "game.addon_supply",
            "game.addon_facing",
            "game.addon_corner",
        },
    )
    assert not report.errors


# --- the switch ------------------------------------------------------------


def test_the_default_arm_is_placed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLAB2BP_COATER_NODE", raising=False)
    assert coater_mode() is CoaterMode.PLACED
    assert coater_mode().is_node


@pytest.mark.parametrize("raw", ["", "  ", "seat", "packed", "packed-hpwl", "nonsense"])
def test_a_retired_or_unknown_arm_falls_back_to_placed(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """The three retired arms are not values any more, and must not be `off`.

    Falling back to `off` would silently reinstate the defect on any stale
    harness that still exports `FLAB2BP_COATER_NODE=seat`.
    """
    monkeypatch.setenv("FLAB2BP_COATER_NODE", raw)
    assert coater_mode() is CoaterMode.PLACED


def test_off_is_still_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLAB2BP_COATER_NODE", "off")
    assert coater_mode() is CoaterMode.OFF
    assert not coater_mode().is_node


# --- the seat rule ---------------------------------------------------------


def test_half_span_is_derived_per_yaw_not_assumed_to_be_one() -> None:
    """Design risk 6: at yaw 0 the body does not extend along the lane at all."""
    assert routing_domain._coater_body_half_span(Facing.EAST.value) == 1
    assert routing_domain._coater_body_half_span(0.0) == 0


def test_off_offers_a_seat_whose_body_covers_the_lane_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect, stated as arithmetic rather than as a blueprint.

    Four lane tiles at ``ox-3 .. ox``: ``_coater_seats`` offers indices 1 and 2,
    and index 1's body is ``{0, 1, 2}`` -- which contains the head.
    """
    _arm(monkeypatch, "off")
    canvas = _Canvas()
    port = _lane_port(canvas, 4)
    seats = routing_domain._coater_seats(canvas, port, west_channel=_COATER_WEST_CHANNEL)
    assert [x for x, _ in seats] == [1, 2]
    half = routing_domain._coater_body_half_span(Facing.EAST.value)
    assert seats[0][0] - half == port.x, "the first seat's body covers the head"


def test_a_narrowed_seat_never_covers_either_routing_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _arm(monkeypatch, "placed")
    canvas = _Canvas()
    assert not routing_domain._coater_seats(
        canvas, _lane_port(canvas, 4), west_channel=_COATER_WEST_CHANNEL
    )
    canvas = _Canvas()
    port = _lane_port(canvas, 5)
    seats = routing_domain._coater_seats(canvas, port, west_channel=_COATER_WEST_CHANNEL)
    assert [x for x, _ in seats] == [2]
    half = routing_domain._coater_body_half_span(Facing.EAST.value)
    assert all(port.x < x - half and x + half < port.x1 for x, _ in seats)


# --- the strip's channel ---------------------------------------------------


def test_off_buys_the_wide_channel_and_placed_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The node's ground is bought back from the consumer strip, per arm."""
    widths: dict[str, set[int]] = {}
    for arm in ("off", "placed"):
        monkeypatch.setenv("FLAB2BP_COATER_NODE", arm)
        strips = [s for s in plan_strips(_spec()) if s.cargo_domain is CargoDomain.REQUIRES_SPRAY]
        assert strips, f"{arm}: fixture stopped asking for a sprayed strip"
        widths[arm] = {s.west_channel for s in strips}
    # At or above `_COATER_WEST_CHANNEL`: a staged-static clearance relation
    # lifts the channel one further, and which strips it lifts is a property of
    # the fixture's machine pose rather than of the arm.
    assert min(widths["off"]) >= _COATER_WEST_CHANNEL
    assert widths["placed"] == {WEST_CHANNEL}


# --- the ban ---------------------------------------------------------------


def test_placed_bans_the_area_one_rival(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Design §5.2, measured on the reported geometry.

    Coater at ``(54, 20, 0)`` with its drop at ``(53, 20, 1)``: the rival
    ``(55, 20)`` -- the cell mirroring the drop across the seat -- loses
    level 1.  The body's own level is NOT banned: that clause was retired on
    the measurement in
    ``test_a_node_body_tile_is_always_an_occupied_belt_so_no_merge_can_be_offered_there``.
    """
    belt_item = catalog.item_id("conveyor-belt-2")
    belt_model = catalog.building(belt_item).model_index
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    body = PlacedBuilding(
        item_id=catalog.SPRAY_COATER_ID,
        model_index=coater.model_index,
        x=54,
        y=20,
        z=F(0),
        width=1,
        height=1,
        yaw=Facing.EAST.value,
    )

    def ban(arm: str) -> dict[tuple[int, int], set[int]]:
        canvas = _Canvas()
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("FLAB2BP_COATER_NODE", arm)
            routing_domain._reserve_coater_belt_ban(canvas, body, belt_model)
        return canvas.belt_ban

    off = ban("off")
    on = ban("placed")
    for x in (53, 54, 55):
        assert 0 not in off.get((x, 20), set())
        assert 0 not in on.get((x, 20), set()), f"body tile {x} keeps its own level, unbanned"
    assert 1 in on[(55, 20)], "the area-1 rival keeps the drop's level"
    assert 1 not in off.get((55, 20), set()), "the rival ban is a node-arm rule only"


def _minimal_node(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_Canvas, _Port, _Port, routing_domain.CoaterSupplyPort]:
    _arm(monkeypatch, "placed")
    canvas = _Canvas()
    node_in, node_out = routing_domain._emit_coater_node(
        canvas,
        0,
        0,
        item="iron-ingot",
        belt_id=2002,
        belt_model=36,
        machines=1,
        owner_strip=0,
    )
    spec = _spec()
    strip = next(s for s in plan_strips(spec) if "iron-ingot" in s.in_lanes)
    supply = routing_domain._place_coaters(
        canvas,
        spec,
        [strip],
        [{"iron-ingot": node_in}],
        2002,
        36,
        policy=BandPolicy("200"),
    )[0]
    return canvas, node_in, node_out, supply


@pytest.mark.parametrize("yaw,axis", [(0, (0, 1)), (90, (1, 0)), (180, (0, -1)), (270, (-1, 0))])
def test_router_turns_start_outside_the_whole_coater_body(
    monkeypatch: pytest.MonkeyPatch, yaw: int, axis: tuple[int, int]
) -> None:
    """The game checks neighboring endpoints of every overlapped existing belt.

    Checking only the ridden belt misses a turn on the downstream body tile.
    BuildTool_BlueprintPaste.cs:145813-145853 rejects that re-paste geometry.
    """
    canvas, node_in, node_out, supply = _minimal_node(monkeypatch)
    coater = canvas.buildings[supply.coater]
    half = routing_domain._coater_body_half_span(coater.yaw)
    assert node_in.x < coater.x - half
    assert node_out.x > coater.x + half
    candidates = routing_domain._coater_seats(canvas, node_in, west_channel=len(node_in.tiles) - 1)
    assert all(node_in.x < x - half and x + half < node_out.x for x, _ in candidates)
    # Real asset boxes, in all four orientations. An arbitrary router turn can
    # start here only when the port's 0.23-world-unit probe clears the body.
    pose = colliders.Placed(coater.model_index, 0, 0, 0, yaw)
    boxes = colliders.target_boxes(pose, *colliders.flat_pose(0, 0, 0, yaw))
    for port in (node_in, node_out):
        distance = port.x - coater.x
        point, _ = colliders.flat_pose(axis[0] * distance, axis[1] * distance, 0, yaw)
        probe = (point[0], point[1] + 0.2, point[2])
        assert not any(colliders.sphere_box_overlap(probe, 0.23, box) for box in boxes)


def test_proliferator_terminal_enters_the_transverse_addon_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shipped AddonPass requires an endpoint's axis dot product > 0.95.

    SlotConfig area 1 faces 90 degrees from the sprayed belt. A longitudinal
    approach has dot=0 even though its terminal sits at the right area center.
    """
    canvas, _node_in, _node_out, supply = _minimal_node(monkeypatch)
    coater = canvas.buildings[supply.coater]
    drop = canvas.buildings[supply.supply_belt]
    approach = canvas.buildings[supply.approach_belt]
    radial = (drop.x - coater.x, drop.y - coater.y)
    incoming = (drop.x - approach.x, drop.y - approach.y)
    assert radial[0] * incoming[0] + radial[1] * incoming[1] == 0
    assert abs(incoming[0]) + abs(incoming[1]) == 1


def test_transverse_emitted_supply_passes_flat_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas, _node_in, _node_out, _supply = _minimal_node(monkeypatch)
    buildings = tuple(canvas.buildings)
    for _ in range(4):
        report = validate.validate(
            Placement(buildings), only=["game.addon_supply"], expect_power=False
        )
        assert not report.errors, "\n".join(finding.message for finding in report.errors)
        buildings = tuple(
            dataclasses.replace(
                building, x=building.y, y=-building.x, yaw=(building.yaw + 90) % 360
            )
            for building in buildings
        )


def test_node_admission_reserves_the_transverse_supply_approach() -> None:
    canvas = _Canvas()
    assert routing_domain._coater_node_site_is_clear(canvas, 0, 0)
    canvas.add(PlacedBuilding(2002, 36, 1, -1, z=F(1)))
    assert not routing_domain._coater_node_site_is_clear(canvas, 0, 0)


@pytest.mark.parametrize(
    "core,near",
    [
        ((0, 0, 199, 153), (50, 0)),
        ((0, 0, 153, 199), (0, 50)),
    ],
)
def test_node_site_keeps_its_supply_inside_a_legal_band(
    core: tuple[int, int, int, int],
    near: tuple[int, int],
) -> None:
    canvas = _Canvas()
    envelope = finalize.band_policy_search_envelope(
        BandPolicy("portable"), perimeter=routing_domain._ENTRY_RING
    )

    def fits(site: tuple[int, int]) -> bool:
        x, y = site
        width = max(core[2], x + routing_domain._COATER_NODE_TILES - 1) - min(core[0], x) + 1
        height = max(core[3], y) - min(core[1], y - 1) + 1
        return bool(envelope.frame_candidates(width, height))

    nearest = routing_domain._coater_node_site(canvas, near, core=core, envelope=None)
    assert nearest is not None and not fits(nearest)
    admitted = routing_domain._coater_node_site(canvas, near, core=core, envelope=envelope)
    assert admitted is not None and fits(admitted)


# --- end to end ------------------------------------------------------------


def _build(arm: str, monkeypatch: pytest.MonkeyPatch) -> object:
    _arm(monkeypatch, arm)
    strategy = FreeformLayout(belt_rules=_BELT_RULES, band_policy=BandPolicy("portable"), workers=2)
    return strategy.lay_out(_spec(), time_budget_s=PROLIFERATED_BUDGET_S)


def _coater_bodies(placement: object) -> list[tuple[int, list[tuple[int, int, F]]]]:
    bs = placement.buildings  # type: ignore[attr-defined]
    out = []
    for i, b in enumerate(bs):
        if b.item_id != catalog.SPRAY_COATER_ID:
            continue
        half = (catalog.oriented_footprint(catalog.SPRAY_COATER_ID, b.yaw)[0] - 1) // 2
        out.append((i, [(b.x + dx, b.y, b.z) for dx in range(-half, half + 1)]))
    return out


def test_a_node_arm_keeps_the_ridden_belt_straight_and_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The node's geometry, pinned where the game reads it.

    The ridden belt has a straight predecessor and a straight successor, both
    on the addon's axis (``rules.addon_ride_is_straight``); the in-port is one
    tile west of the body so a router turn onto it is not a turn on the
    addon's tile (``game.addon_corner``); and the proliferator drop sits one
    level above the tile behind the seat.
    """
    placement = _build("placed", monkeypatch)
    bs = placement.buildings  # type: ignore[attr-defined]
    at = {(b.x, b.y, b.z): i for i, b in enumerate(bs) if is_belt(b.item_id)}
    bodies = _coater_bodies(placement)
    assert bodies, "the fixture stopped asking for a coater"
    for index, cells in bodies:
        c = bs[index]
        west, seat, east = cells
        assert at.get(west) is not None and at.get(east) is not None
        ridden = at[(c.x, c.y, c.z)]
        # A straight predecessor and a straight successor, both belts.
        assert bs[at[west]].output_obj == ridden
        assert bs[ridden].output_obj == at[east]
        # The IN-PORT is one further west and is NOT a body tile.
        in_cell = (west[0] - 1, west[1], west[2])
        assert at.get(in_cell) is not None, "the node's in-port is off the body"
        assert bs[at[in_cell]].output_obj == at[west]
        # The proliferator drop, one level up over the tile behind the seat.
        assert (west[0], west[1], F(1)) in at


def test_no_coater_body_covers_a_belt_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property this whole branch is about, asked of a real build."""
    placement = _build("placed", monkeypatch)
    bs = placement.buildings  # type: ignore[attr-defined]
    at = {(b.x, b.y, b.z): i for i, b in enumerate(bs) if is_belt(b.item_id)}
    predecessors: dict[int, int] = {}
    for b in bs:
        if not is_belt(b.item_id):
            continue
        if b.output_obj is not None and 0 <= b.output_obj < len(bs):
            predecessors[b.output_obj] = predecessors.get(b.output_obj, 0) + 1
    for _index, cells in _coater_bodies(placement):
        for cell in cells:
            belt = at.get(cell)
            if belt is None:
                continue
            assert predecessors.get(belt, 0) <= 1, f"merge under the body at {cell}"


def test_a_node_arm_leaves_the_consumer_lane_ordinary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No sorter touches a coater's belt run under a node arm.

    Which is the structural claim.  Today the addon rides the consumer strip's
    own input lane, so the run it sits on is the run the machines draw from and
    the coater's correctness is an argument about where on that run it sits.
    On a node the run feeds one net, and no sorter can
    reach it at all -- the consumer's lane is an ordinary lane again.
    """
    placement = _build("placed", monkeypatch)
    bs = placement.buildings  # type: ignore[attr-defined]
    succ = {i: b.output_obj for i, b in enumerate(bs) if is_belt(b.item_id)}
    pred: dict[int, list[int]] = {}
    for i, nxt in succ.items():
        if nxt is not None and 0 <= nxt < len(bs) and is_belt(bs[nxt].item_id):
            pred.setdefault(nxt, []).append(i)
    at = {(b.x, b.y, b.z): i for i, b in enumerate(bs) if is_belt(b.item_id)}
    touched = {
        obj
        for b in bs
        if catalog.is_sorter(b.item_id)
        for obj in (b.input_obj, b.output_obj)
        if obj is not None
    }
    assert _coater_bodies(placement), "the fixture stopped asking for a coater"
    for _index, cells in _coater_bodies(placement):
        run = [at[cell] for cell in cells if cell in at]
        assert run, "a coater with no belt under it is not a coater"
        for belt in run:
            assert belt not in touched, "a sorter reaches the node's run"
            assert len(pred.get(belt, ())) <= 1
