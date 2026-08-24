"""Re-derive every real sorter's slots from its own geometry.

The corpus is the only oracle here: eleven blueprints the game itself wrote,
1288 sorters between them.  ``flab2bp.layout.slots`` claims their slot indices
are a function of geometry; these tests hold it to that claim rather than to a
table copied out of the same measurement.

An `Artificial Star` exclusion is the one hole, and it is a data hole rather
than a rule hole -- see :func:`test_only_artificial_star_is_excluded`.
"""

from __future__ import annotations

import collections
import math
from collections.abc import Callable
from pathlib import Path

import pytest

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import colliders
from flab2bp.dsp.codec import decode
from flab2bp.dsp.envelope import BlueprintFormatError
from flab2bp.dsp.records import Blueprint, BlueprintBuilding
from flab2bp.layout import slots as S
from flab2bp.layout import validate as V
from flab2bp.layout.base import PlacedBuilding

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

#: Item id of the Artificial Star.  Its records in the polar `tillable-...`
#: fixture put the sorter end tens of tiles from the building it names, so no
#: geometric rule can be checked against them; see the exclusion test.
ARTIFICIAL_STAR = 2210


def _factory_blueprints() -> list[tuple[str, Blueprint]]:
    out: list[tuple[str, Blueprint]] = []
    for path in sorted(FIXTURES.glob("*.txt")):
        try:
            out.append((path.name, decode(path.read_text().strip())))
        except BlueprintFormatError:
            # `dyson-sphere-iridescent` is a DYBP, not a factory blueprint.
            continue
    return out


def _sorter_sides(
    bp: Blueprint,
) -> list[
    tuple[
        BlueprintBuilding,
        BlueprintBuilding | None,
        int,
        tuple[float, float],
        tuple[float, float],
    ]
]:
    """``(sorter, peer, recorded_slot, end, other_end)`` for both ends of each sorter."""
    by_index = {b.index: b for b in bp.buildings}
    rows = []
    for s in bp.buildings:
        if not cat.is_sorter(s.item_id):
            continue
        rows.append(
            (s, by_index.get(s.output_obj_idx), s.output_to_slot, (s.x2, s.y2), (s.x, s.y))
        )
        rows.append(
            (s, by_index.get(s.input_obj_idx), s.input_from_slot, (s.x, s.y), (s.x2, s.y2))
        )
    return rows


CORPUS = _factory_blueprints()


def test_corpus_loaded() -> None:
    """Guard against a silently empty oracle."""
    assert len(CORPUS) == 10
    total = sum(
        1 for _, bp in CORPUS for b in bp.buildings if cat.is_sorter(b.item_id)
    )
    assert total == 1288


def test_sorter_own_ends_are_constant() -> None:
    """``output_from_slot == 0`` and ``input_to_slot == 1`` on every real sorter."""
    seen = collections.Counter(
        (b.output_from_slot, b.input_to_slot)
        for _, bp in CORPUS
        for b in bp.buildings
        if cat.is_sorter(b.item_id)
    )
    assert dict(seen) == {(S.OUTPUT_FROM_SLOT, S.INPUT_TO_SLOT): 1288}


def test_belt_side_is_always_minus_one() -> None:
    values = collections.Counter(
        slot
        for _, bp in CORPUS
        for _s, peer, slot, _e, _o in _sorter_sides(bp)
        if peer is not None and cat.is_belt(peer.item_id)
    )
    assert dict(values) == {S.BELT_SLOT: 1240}


#: How far off the integer grid a machine may sit and still be trusted as
#: geometry.  Polar blueprints compress longitude with latitude, so near a pole
#: a whole tile of x collapses into a fraction of one and distances stop meaning
#: tiles -- which is the same reason ``dsp.codec.tile_to_local_offset`` was
#: verified on only the three uncompressed fixtures.
ON_GRID_TOLERANCE = 0.2


def _off_grid(b: BlueprintBuilding) -> bool:
    return max(abs(b.x - round(b.x)), abs(b.y - round(b.y))) > ON_GRID_TOLERANCE


def test_machine_slots_reproduce_the_corpus() -> None:
    """The rule reproduces the game's own index on every on-grid record.

    This is the whole point of the module: 1206 machine-side records across
    seven building types, four machine yaws and three footprints, each one
    re-derived from the machine's position, footprint and yaw plus the sorter's
    two endpoints -- nothing read back from the record being checked.
    """
    checked = 0
    wrong: list[str] = []
    for name, bp in CORPUS:
        for _s, peer, slot, end, other in _sorter_sides(bp):
            if peer is None or cat.is_belt(peer.item_id):
                continue
            if peer.item_id == ARTIFICIAL_STAR or _off_grid(peer):
                continue
            got = S.machine_slot(
                peer.item_id,
                peer.yaw,
                (end[0] - peer.x, end[1] - peer.y),
                (end[0] - other[0], end[1] - other[1]),
            )
            checked += 1
            if got != slot:
                wrong.append(
                    f"{name}: {cat.building(peer.item_id).name} at "
                    f"({peer.x:.2f},{peer.y:.2f}) yaw={peer.yaw:.1f} "
                    f"end=({end[0]:.2f},{end[1]:.2f}) game={slot} derived={got}"
                )
    assert checked == 1206
    assert wrong == [], f"{len(wrong)} of {checked} mis-derived:\n" + "\n".join(wrong[:20])


def test_latitude_compressed_records_are_bounded() -> None:
    """The off-grid remainder is small, named, and does not grow silently.

    41 machine-side records sit on machines the polar projection pushed off the
    tile grid.  The few that do not come out right are all Depot Mk.I in
    ``factory-endgame-distribution-hub``, where the sorter's whole x extent has
    been squashed to ~0.1 tiles and the approach direction can no longer be read
    off it.  That is the coordinate system failing, not the slot table -- but it
    is a hole, so it is counted rather than hidden.  Reading the game's own slot
    poses instead of an inferred ring took it from 5 to 3.
    """
    total = 0
    wrong: list[tuple[str, str]] = []
    for name, bp in CORPUS:
        for _s, peer, slot, end, other in _sorter_sides(bp):
            if peer is None or cat.is_belt(peer.item_id):
                continue
            if peer.item_id == ARTIFICIAL_STAR or not _off_grid(peer):
                continue
            total += 1
            got = S.machine_slot(
                peer.item_id,
                peer.yaw,
                (end[0] - peer.x, end[1] - peer.y),
                (end[0] - other[0], end[1] - other[1]),
            )
            if got != slot:
                wrong.append((name, cat.building(peer.item_id).name))
    assert total == 41
    assert wrong == [("factory-endgame-distribution-hub.txt", "Depot Mk.I")] * 3


def test_the_slot_poses_are_what_the_corpus_lands_on() -> None:
    """The game's table, not a ring: every real end is beside the pose it names.

    ``test_machine_slots_reproduce_the_corpus`` shows the *selection* rule picks
    the game's index.  This shows the *table* is the game's, by measuring each
    real sorter end against the pose its recorded index resolves to and holding
    it to the game's own ``0.8`` and its own facing test.  A wrong axis mapping
    -- Unity's ``(x, y, z)`` onto our ``(x, z, y)`` -- puts 779 of these ends a
    tile or more from the slot they name, so it is not a formality.

    The two filters are the same latitude-compression exclusion used everywhere
    else: near a pole a tile of longitude collapses, and neither the sorter's
    length nor the machine's position is in tiles any more.
    """
    checked = 0
    worst_gap = 0.0
    worst_dot = 1.0
    for _name, bp in CORPUS:
        for s, peer, slot, end, other in _sorter_sides(bp):
            if peer is None or cat.is_belt(peer.item_id) or peer.item_id == ARTIFICIAL_STAR:
                continue
            # Tighter than `_off_grid`: measuring a 0.8-tile tolerance needs the
            # machine ON the grid, not merely near it. At the 0.2 the slot-index
            # tests use, six more records come in from the compressed band and
            # one of them reads 0.909 -- a machine two tenths of a tile out
            # cannot be held to a tenth-of-a-tile margin.
            if max(abs(peer.x - round(peer.x)), abs(peer.y - round(peer.y))) > 0.02:
                continue
            if not 0.9 <= math.dist((s.x, s.y), (s.x2, s.y2)) <= 3.2:
                continue
            dx, dy, dz = S.slot_offset(peer.item_id, peer.yaw, slot)
            gap = S.world_gap(peer.x + dx - end[0], peer.y + dy - end[1], dz)
            fx, fy, _fz = S.slot_forward(peer.item_id, peer.yaw, slot)
            away = (other[0] - end[0], other[1] - end[1])
            n = math.hypot(*away) or 1.0
            checked += 1
            worst_gap = max(worst_gap, gap)
            worst_dot = min(worst_dot, (fx * away[0] + fy * away[1]) / n)
    assert checked == 1142
    # 0.113, not "just inside 0.8". The first version of this test compared a
    # TILE distance with a WORLD limit and reported 0.774 -- inside, and cited
    # as proof. It proved nothing: 0.8 is loose enough that the wrong scale
    # passes too, so the control could not tell the two apart. Held to a tenth
    # of the limit it can: at the wrong scale this reads 0.774 and fails.
    assert worst_gap <= S.SLOT_REACH / 5.0, f"worst gap {worst_gap}"
    assert worst_dot >= 0.0, f"worst dot {worst_dot}"


def test_world_gap_scales_tiles_and_levels_differently() -> None:
    """A tile and a level are different sizes, and neither is 1.

    The game's 0.8 is a Unity ``Vector3.magnitude``, so a grid-frame offset has
    to be scaled before it is compared with one.  Both axes, because a corpus
    whose worst record happens to lie along x cannot tell you whether y is
    scaled at all.
    """
    assert S.world_gap(1.0, 0.0) == pytest.approx(colliders.GRID_ARC)
    assert S.world_gap(0.0, 1.0) == pytest.approx(colliders.GRID_ARC)
    assert S.world_gap(0.0, 0.0, 1.0) == pytest.approx(cat.WORLD_UNITS_PER_LEVEL)
    assert pytest.approx(1.2566, abs=1e-4) == colliders.GRID_ARC
    assert S.world_gap(1.0, 1.0) == pytest.approx(colliders.GRID_ARC * math.sqrt(2))


def test_the_length_and_skew_ladder_reads_the_raw_blueprint() -> None:
    """923 real sorters clear the game's length and TooSkew ladder, read RAW.

    This test exists because the first port of that ladder read it against the
    SNAPPED positions and the corpus threw it out: 11 Oil Refinery records in
    ``factory-quick-start-step-3-red-cube``, a blueprint the game ships, come
    out 0.45 tiles long and 29.9 degrees off axis that way.  Read as the
    blueprint carries them, the tightest record clears its length minimum by
    0.511 and the worst end is 9.9 degrees off against a limit of 24.

    Margins, not just a pass, because "everything passes" is also what a check
    that reads nothing would report.
    """
    checked = 0
    slack = 9.9
    worst_pair = worst_axis = 0.0
    for _name, bp in CORPUS:
        by_index = {b.index: b for b in bp.buildings}
        for s in bp.buildings:
            if not cat.is_sorter(s.item_id):
                continue
            if not 0.9 <= math.dist((s.x, s.y), (s.x2, s.y2)) <= 3.2:
                continue
            peers = [by_index.get(s.input_obj_idx), by_index.get(s.output_obj_idx)]
            if any(p is None for p in peers) or any(p.item_id == ARTIFICIAL_STAR for p in peers):
                continue
            if any(_off_grid(p) for p in peers):
                continue
            belts = sum(1 for p in peers if cat.is_belt(p.item_id))
            length = math.dist((s.x, s.y), (s.x2, s.y2))
            low, high = V._SORTER_LENGTH[belts]
            assert length <= high, f"{length} over {high}"
            slack = min(slack, length - low)
            f1 = _forward(s.yaw)
            f2 = _forward(s.yaw2)
            axis = _forward(math.degrees(math.atan2(s.x2 - s.x, s.y2 - s.y)))
            worst_pair = max(worst_pair, _angle(f1, f2))
            worst_axis = max(worst_axis, max(_off_axis(axis, f1), _off_axis(axis, f2)))
            checked += 1
    assert checked == 940
    assert slack >= 0.5, f"tightest length clears its floor by only {slack}"
    assert worst_pair <= V._SKEW_PAIR_DEG, worst_pair
    assert worst_axis <= V._SKEW_AXIS_DEG, worst_axis


def _forward(yaw: float) -> tuple[float, float]:
    return (math.sin(math.radians(yaw)), math.cos(math.radians(yaw)))


def _angle(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))))


def _off_axis(axis: tuple[float, float], f: tuple[float, float]) -> float:
    return math.degrees(math.acos(min(1.0, abs(axis[0] * f[0] + axis[1] * f[1]))))


def test_only_artificial_star_is_excluded() -> None:
    """The one exclusion is a broken *record*, not a building we cannot model.

    In the polar ``tillable-...`` fixture a sorter names an Artificial Star tens
    of tiles away -- 24 of its 88 records put the sorter end outside the star's
    footprint entirely and 62 more put it in the interior.  There is no geometry
    to check there.  Every other machine-side record in the corpus has its end
    on the named building's perimeter, and this test fails if that ever stops
    being true, so the exclusion can never quietly widen.
    """
    far = 0
    for _name, bp in CORPUS:
        for _s, peer, _slot, end, _other in _sorter_sides(bp):
            if peer is None or cat.is_belt(peer.item_id):
                continue
            b = cat.building(peer.item_id)
            dx = abs(end[0] - peer.x)
            dy = abs(end[1] - peer.y)
            outside = dx > (b.width - 1) / 2 + 0.5 or dy > (b.height - 1) / 2 + 0.5
            if outside:
                assert peer.item_id == ARTIFICIAL_STAR, (
                    f"{b.name} record has its sorter end outside the footprint; "
                    f"the exclusion list would have to grow"
                )
                far += 1
    assert far == 24


@pytest.mark.parametrize(
    ("offset", "approach", "expected"),
    [
        # 3x3, un-mirrored, every one of the twelve slots.
        ((-1, 1), (0, -1), 0),
        ((0, 1), (0, -1), 1),
        ((1, 1), (0, -1), 2),
        ((1, 1), (-1, 0), 3),
        ((1, 0), (-1, 0), 4),
        ((1, -1), (-1, 0), 5),
        ((1, -1), (0, 1), 6),
        ((0, -1), (0, 1), 7),
        ((-1, -1), (0, 1), 8),
        ((-1, -1), (1, 0), 9),
        ((-1, 0), (1, 0), 10),
        ((-1, 1), (1, 0), 11),
    ],
)
def test_unmirrored_ring(
    offset: tuple[int, int], approach: tuple[int, int], expected: int
) -> None:
    assert S.machine_slot(2303, 0.0, offset, approach) == expected


@pytest.mark.parametrize(
    ("offset", "approach", "expected"),
    [
        # 5x5 Matrix Lab, mirrored, every one of the twelve slots.
        ((1, 2), (0, -1), 0),
        ((0, 2), (0, -1), 1),
        ((-1, 2), (0, -1), 2),
        ((-2, 1), (1, 0), 3),
        ((-2, 0), (1, 0), 4),
        ((-2, -1), (1, 0), 5),
        ((-1, -2), (0, 1), 6),
        ((0, -2), (0, 1), 7),
        ((1, -2), (0, 1), 8),
        ((2, -1), (-1, 0), 9),
        ((2, 0), (-1, 0), 10),
        ((2, 1), (-1, 0), 11),
    ],
)
def test_mirrored_ring(
    offset: tuple[int, int], approach: tuple[int, int], expected: int
) -> None:
    assert S.machine_slot(2901, 0.0, offset, approach) == expected


@pytest.mark.parametrize("yaw", [0.0, 90.0, 180.0, 270.0])
def test_yaw_rotates_the_ring(yaw: float) -> None:
    """Turning the machine turns its ring with it, so the slot is unchanged."""
    rot: dict[float, Callable[[int, int], tuple[int, int]]] = {
        0.0: lambda x, y: (x, y),
        90.0: lambda x, y: (y, -x),
        180.0: lambda x, y: (-x, -y),
        270.0: lambda x, y: (-y, x),
    }
    turn = rot[yaw]
    for offset, approach, expected in (
        ((-1, 1), (0, -1), 0),
        ((1, 0), (-1, 0), 4),
        ((0, -1), (0, 1), 7),
        ((-1, 0), (1, 0), 10),
    ):
        assert S.machine_slot(2303, yaw, turn(*offset), turn(*approach)) == expected


def test_wide_side_clamps_to_its_end_slot() -> None:
    """A side has three slots however long it is, so a far column takes the end one.

    The Matrix Lab's north side is five tiles but carries slots only at
    ``x in {-1, 0, 1}``, so a column further out has no slot beside it and the
    nearest one on that face is named instead.  ``game.inserter_data`` is what
    reports that end as too far to paste; this only pins which slot it lands on.
    """
    assert S.machine_slot(2901, 0.0, (4, 2), (0, -1)) == 0
    assert S.machine_slot(2901, 0.0, (-4, 2), (0, -1)) == 2


def test_a_diagonal_approach_now_resolves() -> None:
    """It used to be refused; with real poses there is nothing left to refuse on.

    The old ring needed the approach to name a side, so an exactly diagonal one
    was ambiguous.  A pose table is not ambiguous: slot 2 is the nearest slot
    the sorter runs towards, whatever mixture of x and y it arrived by.
    """
    assert S.machine_slot(2303, 0.0, (1, 1), (-1, -1)) == 2


def _at(item_id: int, x: int = 0, y: int = 0) -> PlacedBuilding:
    b = cat.building(item_id)
    return PlacedBuilding(
        item_id=item_id, model_index=b.model_index, x=x, y=y, width=b.width, height=b.height
    )


def test_attachment_puts_a_3x3_sorter_on_the_edge_row() -> None:
    """The easy case, and the one every wrong rule also got right."""
    m = _at(2303)  # 3x3 at (0,0), so rows 0..2
    got = S.attachment(m, (1, 3))
    assert got is not None
    assert got.cell == (1, 2)
    assert got.span == 1


def test_attachment_reaches_a_chemical_plants_inner_row() -> None:
    """Its southern slots are a row INSIDE a footprint five deep.

    So the sorter is two tiles long and its machine end is not on the edge --
    the single fact that made every Chemical Plant blueprint we shipped paste
    with "Sorter data error".
    """
    m = _at(2309)  # 9x5 at (0,0): columns 0..8, rows 0..4
    got = S.attachment(m, (4, -1))
    assert got is not None
    assert got.cell == (4, 1), "one row in from the southern edge"
    assert got.span == 2


def test_attachable_columns_are_the_ones_the_table_has() -> None:
    """Four of a Chemical Plant's nine columns, three of a Matrix Lab's five."""
    plant = _at(2309)
    assert sorted(S.attachable_columns(plant, -1)) == [3, 4, 5, 6]
    assert sorted(S.attachable_columns(plant, 5)) == [3, 4, 5, 6]
    lab = _at(2901)
    assert sorted(S.attachable_columns(lab, -1)) == [1, 2, 3]


def test_an_oil_refinery_cannot_be_served_from_the_north_at_all() -> None:
    """Nine slots, none of them on that face.

    Not a clamp and not a near miss -- there is no pose to be near.  A layout
    that runs its lanes east-west can only serve a Refinery from below, and
    saying so is the point: the alternative is a sorter the game deletes.
    """
    refinery = _at(2308)  # 3x7
    assert S.attachable_columns(refinery, 7) == {}
    assert sorted(S.attachable_columns(refinery, -1)) == [0, 1, 2]


def test_attachment_refuses_a_lane_further_than_a_sorter_reaches() -> None:
    """A Chemical Plant's inner row costs a tile of span before anything else.

    Its only southern pose anchors on row 1 of a five-deep footprint, so a lane
    three tiles clear of the building is already a four-tile sorter -- past
    ``SORTER_MAX_REACH`` -- and there is no second pose further out to fall back
    to.  A wide machine is not merely awkward to serve, it is served from
    CLOSER than a 3x3 needs to be.
    """
    plant = _at(2309)  # rows 0..4
    assert S.attachment(plant, (4, -2)) is not None, "three tiles is still legal"
    assert S.attachment(plant, (4, -3)) is None


def test_a_belt_addon_carries_the_pair_the_game_writes() -> None:
    """All eight corpus coaters: no connection, and ``(15, 14)`` on both ends."""
    seen = collections.Counter()
    links = collections.Counter()
    for _name, bp in CORPUS:
        for b in bp.buildings:
            if b.item_id != cat.SPRAY_COATER_ID:
                continue
            seen[
                (b.output_from_slot, b.output_to_slot, b.input_from_slot, b.input_to_slot)
            ] += 1
            links[(b.output_obj_idx, b.input_obj_idx)] += 1
    assert dict(seen) == {
        (S.ADDON_FROM_SLOT, S.ADDON_TO_SLOT, S.ADDON_FROM_SLOT, S.ADDON_TO_SLOT): 8
    }
    assert dict(links) == {(-1, -1): 8}, "a coater is wired to nothing"


def test_an_oil_refinery_is_turned_a_quarter_and_nothing_else_is() -> None:
    """The one building whose upright orientation cannot be wired at all.

    Nine poses and not one facing north, so a layout with east-west lanes can
    only ever feed it from below -- which is why every Refinery spec refused.
    Turned, it presents three poses to each side.  Everything else stays
    upright: the rule prefers an orientation reachable from BOTH sides and
    breaks ties toward zero, so nothing rotates without cause.
    """
    assert S.lane_orientation(2308) == 90.0  # Oil Refinery
    assert S.lane_facing(2308, 0.0) == (False, True)
    assert S.lane_facing(2308, 90.0) == (True, True)
    for other in (2303, 2302, 2901, 2309, 2101):
        assert S.lane_orientation(other) == 0.0, other


def test_turning_a_refinery_makes_both_sides_reachable() -> None:
    """The point of the rotation, stated as the thing that changed."""
    upright = S.probe_building(2308, 0.0)
    assert (upright.width, upright.height) == (3, 7)
    assert S.attachable_columns(upright, upright.height) == {}

    turned = S.probe_building(2308, 90.0)
    assert (turned.width, turned.height) == (7, 3), "a quarter turn swaps the extents"
    assert sorted(S.attachable_columns(turned, turned.height)) == [2, 3, 4]
    assert sorted(S.attachable_columns(turned, -1)) == [2, 3, 4]


def test_the_chosen_orientation_is_never_worse_than_the_other() -> None:
    """Over the whole catalog, and it is the property the two keys exist for.

    ``lane_orientation`` ranks by "reachable from both sides" and then by
    "reachable from either".  Both keys are meaningful, but NO shipped building
    tells their ORDER apart -- swapping them changes no answer, so no test can
    witness the order and none pretends to.  What is witnessed is the property
    that would actually break: the orientation chosen is at least as reachable
    as the one rejected, on both counts.
    """
    for b in cat.all_buildings():
        if not b.slot_poses:
            continue
        chosen = S.lane_orientation(b.item_id)
        other = 90.0 if chosen == 0.0 else 0.0
        cn, cs = S.lane_facing(b.item_id, chosen)
        on, os_ = S.lane_facing(b.item_id, other)
        assert (cn and cs) >= (on and os_), b.name
        assert (cn or cs) >= (on or os_), b.name


def test_a_building_with_no_poses_is_left_upright() -> None:
    """No orientation helps a Ray Receiver, so none is claimed to."""
    assert S.lane_orientation(2208) == 0.0


def test_attachment_is_empty_for_a_building_that_takes_no_sorter() -> None:
    assert S.attachment(_at(2208), (4, -1)) is None  # Ray Receiver
    assert S.attachment(_at(2209), (4, -1)) is None  # Energy Exchanger


def test_a_building_with_no_sorter_slots_is_refused() -> None:
    """Storage Tank: four belt PORTS, and not one insert pose.

    This is the distinction ``buildings.json`` blurred -- its ``slots`` field is
    the port table -- and naming a slot on a building that has none is the shape
    of guess this module exists to stop.
    """
    assert cat.building(2106).slots, "Storage Tank does have belt ports"
    assert not cat.building(2106).slot_poses
    with pytest.raises(S.SlotUndetermined):
        S.machine_slot(2106, 0.0, (0, 3), (0, 1))


def test_the_chemical_plant_table_is_the_games_and_not_a_ring() -> None:
    """Eight slots in two rows, and neither long side takes a sorter at all.

    The building this project kept getting wrong.  Nine tiles wide and five
    deep, but a sorter may only meet it at ``x in {-1, 0, 1, 2}`` on the north
    face, or on the row one tile INSIDE the south edge.  No ring rule produces
    that, and the ring rule this module used to carry predicted twelve slots on
    a mirrored ring -- which is why a three-building blueprint with a Chemical
    Plant in it pasted as "Sorter data error" while the same shape built from
    3x3 assemblers pasted clean.
    """
    poses = cat.building(2309).slot_poses
    assert len(poses) == 8
    assert sorted({round(p.dy, 2) for p in poses}) == [-0.9, 2.1]
    assert sorted(round(p.dx, 2) for p in poses if p.dy > 0) == [-1.0, 0.0, 1.0, 2.0]
    # The north face slots face north, the inner row faces south.
    assert all(p.fy > 0.9 for p in poses if p.dy > 0)
    assert all(p.fy < -0.9 for p in poses if p.dy < 0)
