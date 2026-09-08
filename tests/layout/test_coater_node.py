"""``FLAB2BP_COATER_NODE``: each arm's emitted geometry, pinned.

Two arms, compared on the same tree rather than argued about.  The measured
evidence that chose between them is
``docs/superpowers/evidence/2026-09-07-exp-coater-node/README.md``.

``placed``
    The default and the production model.  The Spray Coater as a real node: a
    four-tile belt run with the addon on its third tile, its in-port and
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

from flab2bp.dsp import catalog
from flab2bp.dsp.records import is_belt
from flab2bp.layout import freeform
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.coater_mode import CoaterMode, coater_mode
from flab2bp.layout.freeform import (
    _COATER_WEST_CHANNEL,
    WEST_CHANNEL,
    FreeformLayout,
    Strip,
    _Canvas,
    _Port,
    plan_strips,
)
from flab2bp.layout.strip_variants import CargoDomain
from flab2bp.spec import BuildSpec, MachineGroup, ProliferatorMode

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
            freeform.PlacedBuilding(
                item_id=catalog.item_id("conveyor-belt-2"),
                model_index=catalog.building(catalog.item_id("conveyor-belt-2")).model_index,
                x=x,
                y=0,
                width=1,
                height=1,
                yaw=freeform.Facing.EAST.value,
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


def test_strip_has_no_coater_node_field() -> None:
    """The packed arms are gone, so no Strip is a rectangle of belt."""
    assert "coater_node" not in {f.name for f in dataclasses.fields(Strip)}


# --- the seat rule ---------------------------------------------------------


def test_half_span_is_derived_per_yaw_not_assumed_to_be_one() -> None:
    """Design risk 6: at yaw 0 the body does not extend along the lane at all."""
    assert freeform._coater_body_half_span(freeform.Facing.EAST.value) == 1
    assert freeform._coater_body_half_span(0.0) == 0


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
    seats = freeform._coater_seats(canvas, port, west_channel=_COATER_WEST_CHANNEL)
    assert [x for x, _ in seats] == [1, 2]
    half = freeform._coater_body_half_span(freeform.Facing.EAST.value)
    assert seats[0][0] - half == port.x, "the first seat's body covers the head"


def test_a_narrowed_seat_never_covers_its_own_in_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _arm(monkeypatch, "placed")
    canvas = _Canvas()
    port = _lane_port(canvas, 4)
    seats = freeform._coater_seats(canvas, port, west_channel=_COATER_WEST_CHANNEL)
    assert [x for x, _ in seats] == [2]
    half = freeform._coater_body_half_span(freeform.Facing.EAST.value)
    assert all(x - half > port.x for x, _ in seats)


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
    body = freeform.PlacedBuilding(
        item_id=catalog.SPRAY_COATER_ID,
        model_index=coater.model_index,
        x=54,
        y=20,
        z=F(0),
        width=1,
        height=1,
        yaw=freeform.Facing.EAST.value,
    )

    def ban(arm: str) -> dict[tuple[int, int], set[int]]:
        canvas = _Canvas()
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("FLAB2BP_COATER_NODE", arm)
            freeform._reserve_coater_belt_ban(canvas, body, belt_model)
        return canvas.belt_ban

    off = ban("off")
    on = ban("placed")
    for x in (53, 54, 55):
        assert 0 not in off.get((x, 20), set())
        assert 0 not in on.get((x, 20), set()), f"body tile {x} keeps its own level, unbanned"
    assert 1 in on[(55, 20)], "the area-1 rival keeps the drop's level"
    assert 1 not in off.get((55, 20), set()), "the rival ban is a node-arm rule only"


# --- end to end ------------------------------------------------------------


def _build(arm: str, monkeypatch: pytest.MonkeyPatch) -> object:
    _arm(monkeypatch, arm)
    strategy = FreeformLayout(band_policy=BandPolicy("portable"), workers=2)
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


def test_a_node_arm_emits_a_four_tile_run_with_the_addon_on_its_third_tile(
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


def test_a_node_body_tile_is_always_an_occupied_belt_so_no_merge_can_be_offered_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measurement that retired the body-level clause of the coater ban.

    ``_reserve_coater_belt_ban`` used to add the body's own level across
    ``[-body_half, +body_half]`` under a node arm.  A* can never step onto an
    occupied belt, so the only thing that ban could buy is stopping
    ``_merge_frontier`` from OFFERING a body tile as a merge goal -- and the
    frontier offers only cells ``_Canvas.free`` accepts.  So the clause can
    change a routing decision only for a body cell that is free at the moment
    the ban is written.

    None is.  Every body tile is one of the node's own four belts, committed to
    the canvas during emission and therefore long before the coater is staged.
    The clause was a no-op, and this is the proof standing in its place.
    """
    seen: list[tuple[tuple[int, int, int], bool, bool]] = []
    original = freeform._reserve_coater_belt_ban

    def spy(canvas: _Canvas, coater: freeform.PlacedBuilding, belt_model: int) -> None:
        half = freeform._coater_body_half_span(coater.yaw)
        cx, cy, cz = coater.x, coater.y, int(coater.z)
        for dx in range(-half, half + 1):
            cell = (cx + dx, cy, cz)
            carries_belt = any(
                is_belt(building.item_id)
                and (building.x, building.y, building.z) == (*cell[:2], F(cz))
                for building in canvas.buildings
            )
            seen.append((cell, canvas.free(cell), carries_belt))
        original(canvas, coater, belt_model)

    monkeypatch.setattr(freeform, "_reserve_coater_belt_ban", spy)
    _build("placed", monkeypatch)

    assert seen, "the fixture stopped committing a coater"
    assert [cell for cell, free, _ in seen if free] == [], (
        "a node body tile was free when the ban was written -- clause (a) is "
        "load-bearing again and must be restored"
    )
    assert all(carries_belt for _cell, _free, carries_belt in seen), (
        "a node body tile is occupied by something other than the node's belt"
    )


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
    On a node the run is four tiles long, feeds one net, and no sorter can
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
