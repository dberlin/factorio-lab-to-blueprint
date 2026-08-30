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
import dataclasses
import math
from collections.abc import Callable, Sequence
from fractions import Fraction
from pathlib import Path

import pytest

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import colliders
from flab2bp.dsp import rules as R
from flab2bp.dsp.codec import decode
from flab2bp.dsp.envelope import BlueprintFormatError
from flab2bp.dsp.records import Blueprint, BlueprintBuilding
from flab2bp.layout import slots as S
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
    assert S.world_gap(0.0, 0.0, 1.0) == pytest.approx(R.WORLD_UNITS_PER_LEVEL)
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
            # Narrowed in one step rather than guarded twice: the `or` below
            # used to lean on short-circuiting to keep the second half from
            # touching a None, which is correct at runtime and unreadable to a
            # type checker -- and would stay "correct" if someone reordered it.
            linked = [by_index.get(s.input_obj_idx), by_index.get(s.output_obj_idx)]
            if any(p is None for p in linked):
                continue
            peers = [p for p in linked if p is not None]
            if any(p.item_id == ARTIFICIAL_STAR for p in peers):
                continue
            if any(_off_grid(p) for p in peers):
                continue
            belts = sum(1 for p in peers if cat.is_belt(p.item_id))
            length = math.dist((s.x, s.y), (s.x2, s.y2))
            low, high = R.SORTER_LENGTH[belts]
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
    assert worst_pair <= R.SKEW_PAIR_DEG, worst_pair
    assert worst_axis <= R.SKEW_AXIS_DEG, worst_axis


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


@pytest.mark.parametrize(
    ("yaw", "expected"),
    [
        (0.0, (10, 19, 3)),
        (90.0, (9, 20, 3)),
        (180.0, (10, 21, 3)),
        (270.0, (11, 20, 3)),
    ],
)
def test_coater_supply_cell_rotates_behind_host_at_next_level(
    yaw: float, expected: tuple[int, int, int]
) -> None:
    assert S.addon_supply_cell(
        cat.SPRAY_COATER_ID,
        x=10,
        y=20,
        z=Fraction(2),
        yaw=yaw,
        area=1,
    ) == expected


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
    """Four of a Chemical Plant's seven columns, three of a Matrix Lab's five.

    The four are centre-1 .. centre+2, and they still are: when the plant's
    footprint went from 9 wide to 7 its centre column moved from 4 to 3 and
    these moved with it, which is the check that the poses are read off the
    centre and not off the corner.
    """
    plant = _at(2309)
    assert sorted(S.attachable_columns(plant, -1)) == [2, 3, 4, 5]
    assert sorted(S.attachable_columns(plant, 5)) == [2, 3, 4, 5]
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


def test_chemical_lane_three_clear_is_past_real_slot_reach() -> None:
    """The inner north-side pose makes the apparent third clear row too far."""
    plant = _at(2309)
    lane_y = plant.y - cat.SORTER_MAX_REACH

    assert S.attachable_columns(plant, lane_y) == {}


def test_chemical_lane_closer_uses_real_inner_anchor() -> None:
    """One row closer reaches the pose without a machine-name spacing rule."""
    plant = _at(2309)
    lane_y = plant.y - cat.SORTER_MAX_REACH + 1
    attachments = S.attachable_columns(plant, lane_y)

    assert attachments
    assert {attachment.cell[1] for attachment in attachments.values()} == {
        plant.y + 1
    }
    assert max(attachment.span for attachment in attachments.values()) <= (
        cat.SORTER_MAX_REACH
    )


def test_a_belt_addon_carries_the_pair_the_game_writes() -> None:
    """All eight corpus coaters: no connection, and ``(15, 14)`` on both ends."""
    seen: collections.Counter[tuple[int, int, int, int]] = collections.Counter()
    links: collections.Counter[tuple[int, int]] = collections.Counter()
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


def test_a_belt_ported_building_with_no_sorter_slots_is_refused() -> None:
    """Energy Exchanger: four belt ports, and not one authoritative sorter pose."""
    exchanger = cat.building(cat.ENERGY_EXCHANGER_ID)

    assert len(exchanger.slots) == 4, "the Energy Exchanger does have belt ports"
    assert exchanger.slot_poses == ()
    with pytest.raises(S.SlotUndetermined, match="defines no sorter slots at all"):
        S.machine_slot(cat.ENERGY_EXCHANGER_ID, 0.0, (0, 4), (0, 1))


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


# --- the seat, against the only blueprint the game has answered --------------
#
# The user pasted `tests/fixtures/ours/sorter-collide-freeform.txt`, force-built
# it, and blueprinted the result back out as `sorter-collide-built.txt`.  The
# game built 33 of our 38 sorters, and where it put their ends is the only
# direct evidence anywhere of what `RefreshBuildPreview` does to a sorter we
# wrote.  These tests hold `slots.seated_sorter` to it.

OURS = FIXTURES / "ours" / "sorter-collide-freeform.txt"
BUILT = FIXTURES / "ours" / "sorter-collide-built.txt"

#: The built copy is a quarter turn and a translation off ours, solved against
#: all 17 machines and exact to 2e-5.  Buildings are also REORDERED by the game,
#: so nothing may be matched by index.
def _as_built(x: float, y: float) -> tuple[float, float]:
    return (y + 3.0, -x + 27.0)


#: The latitude the COPY was taken at, and the one free parameter in the
#: comparison below.  It is recovered from the 32 machine ends and falls inside
#: the band the built blueprint's own ``area_segments`` of 160 requires -- the
#: game's longitude step is fixed at the anchor's latitude, so a column away
#: from the equator is ``area_segments / 200 / cos(lat)`` of a tile rather than
#: a tile.  Undoing that is what separates the seat model from where the user
#: happened to be standing; `geom.collide` documents the same effect.
_BUILT_LAT = -0.7916790
_BUILT_LNG_STEP = 2.0 * math.pi / (160 * 5)
_LAT_STEP = 2.0 * math.pi / 1000


def _on_sphere(tile: tuple[float, float], off: tuple[float, float]) -> tuple[float, float]:
    """A flat sub-tile offset, carried onto the sphere the copy was taken on.

    ``tile`` is a grid node in the BUILT frame, which maps tile-for-tile; only
    the sub-tile remainder takes the column compression, and it takes it as a
    world displacement rather than as a number of columns.
    """
    lat = _BUILT_LAT + tile[1] * _LAT_STEP
    lng = tile[0] * _BUILT_LNG_STEP
    scale = 0.2 + colliders.PLANET_RADIUS
    base = (
        math.cos(lat) * math.sin(lng) * scale,
        math.sin(lat) * scale,
        math.cos(lat) * -math.cos(lng) * scale,
    )
    # our +y (north) is the built frame's +x (east) after the quarter turn
    east, north = off[1] * colliders.GRID_ARC, -off[0] * colliders.GRID_ARC
    e = (math.cos(lng), 0.0, math.sin(lng))
    n = (-math.sin(lat) * math.sin(lng), math.cos(lat), math.sin(lat) * math.cos(lng))
    p = tuple(base[i] + e[i] * east + n[i] * north for i in range(3))
    norm = math.sqrt(sum(c * c for c in p))
    return (
        math.atan2(p[0], -p[2]) / _BUILT_LNG_STEP,
        (math.asin(p[1] / norm) - _BUILT_LAT) / _LAT_STEP,
    )


def _placed_blueprint(bs: Sequence[BlueprintBuilding]) -> list[PlacedBuilding]:
    """A decoded blueprint as PlacedBuildings, index-aligned so links resolve."""
    out = []
    for b in bs:
        d = cat.building(b.item_id)
        out.append(
            PlacedBuilding(
                item_id=b.item_id,
                model_index=b.model_index,
                x=b.x - (d.width - 1) / 2,  # type: ignore[arg-type]
                y=b.y - (d.height - 1) / 2,  # type: ignore[arg-type]
                z=b.z,  # type: ignore[arg-type]
                width=d.width,
                height=d.height,
                yaw=b.yaw,
                x2=b.x2,  # type: ignore[arg-type]
                y2=b.y2,  # type: ignore[arg-type]
                z2=b.z2,  # type: ignore[arg-type]
                yaw2=b.yaw2,
                input_obj=b.input_obj_idx if b.input_obj_idx >= 0 else None,
                output_obj=b.output_obj_idx if b.output_obj_idx >= 0 else None,
                input_from_slot=b.input_from_slot,
                output_to_slot=b.output_to_slot,
            )
        )
    return out


def _answer_key() -> list[tuple[PlacedBuilding, BlueprintBuilding, list[PlacedBuilding]]]:
    """Our 38 sorters paired with the 33 the game built, matched by POSITION."""
    ours = decode(OURS.read_text(encoding="utf-8")).buildings
    built = decode(BUILT.read_text(encoding="utf-8")).buildings
    placed = _placed_blueprint(ours)
    mine = [b for b in ours if cat.is_sorter(b.item_id)]
    theirs = [b for b in built if cat.is_sorter(b.item_id)]
    scored = []
    for b in mine:
        assert b.x2 is not None and b.y2 is not None
        e1, e2 = _as_built(b.x, b.y), _as_built(b.x2, b.y2)
        d, c = min(
            (max(math.dist(e1, (c.x, c.y)), math.dist(e2, (c.x2, c.y2))), c)
            for c in theirs
        )
        scored.append((d, b, c))
    out, used = [], set()
    for d, b, c in sorted(scored, key=lambda r: r[0]):
        if d > 1.0 or c.index in used:
            continue
        used.add(c.index)
        out.append((placed[b.index], c, placed))
    return out


def _seat_errors(*, drag: bool) -> list[float]:
    """How far each of the 66 built ends is from where the seat says it is."""
    real = S._drag_belt_end
    if not drag:
        S._drag_belt_end = lambda *a, **k: None
    try:
        errs = []
        for b, c, placed in _answer_key():
            seat = S.seated_sorter(b, placed)
            assert seat is not None
            assert b.x2 is not None and b.y2 is not None
            pre = [(b.x, b.y), (b.x2, b.y2)]
            got = [(seat.x, seat.y), (seat.x2, seat.y2)]
            rec = [(c.x, c.y), (c.x2, c.y2)]
            peers = [
                placed[b.input_obj] if b.input_obj is not None else None,
                placed[b.output_obj] if b.output_obj is not None else None,
            ]
            for k in (0, 1):
                p = peers[k]
                anchor = (
                    pre[k]
                    if p is None or cat.is_belt(p.item_id)
                    else (p.x + (p.width - 1) / 2, p.y + (p.height - 1) / 2)
                )
                off = (got[k][0] - anchor[0], got[k][1] - anchor[1])
                errs.append(math.dist(_on_sphere(_as_built(*anchor), off), rec[k]))
    finally:
        S._drag_belt_end = real
    return errs


def test_the_seat_reproduces_every_end_the_game_built() -> None:
    """33 sorters, 66 ends, and the game put every one where this says.

    The five it refused are not here: they are the ones `game.sorter_collide`
    convicts, and the game created no record for them to be compared against.
    """
    errs = _seat_errors(drag=True)
    assert len(errs) == 66
    assert max(errs) < 0.01, f"worst end off by {max(errs):.5f} tiles"


def test_without_the_belt_end_drag_the_seat_is_wrong_by_two_thirds_of_a_tile() -> None:
    """The mutation check on :func:`slots._drag_belt_end`.

    Seating the machine end and leaving the belt end on the tile we wrote is
    not a smaller model, it is a wrong one: `RefreshBuildPreview` slides the
    belt end by the part of the seat delta that is ACROSS the sorter, and on
    this blueprint that is up to 0.638 of a tile.
    """
    errs = _seat_errors(drag=False)
    assert max(errs) > 0.6
    assert sum(e < 0.01 for e in errs) == 41, "only the ends the drag would not have moved"


def _bench() -> tuple[list[PlacedBuilding], PlacedBuilding]:
    """A 3x3 Assembling Machine centred on (5, 5) with a lane two tiles south.

    ``buildings[0]`` is the machine, ``[1..3]`` are lane tiles at y = 2, 0 and
    -2, and the sorter returned reaches from the first of them into the
    machine's south face.
    """
    machine = PlacedBuilding(
        item_id=2304,
        model_index=cat.building(2304).model_index,
        x=4,
        y=4,
        width=3,
        height=3,
    )
    belts = [
        PlacedBuilding(
            item_id=2001, model_index=cat.building(2001).model_index, x=5, y=y
        )
        for y in (2, 0, -2)
    ]
    into = PlacedBuilding(
        item_id=2011,
        model_index=cat.building(2011).model_index,
        x=5,
        y=2,
        x2=5,
        y2=4,
        z2=Fraction(0),
        input_obj=1,
        output_obj=0,
    )
    return [machine, *belts], into


def test_a_sorter_still_carrying_its_default_slots_seats_on_the_real_one() -> None:
    """The seat is the SLOT, and a strategy has not assigned one yet.

    A sorter comes out of a strategy with the dataclass default of zero in all
    four slot fields; ``assign_sorter_slots`` fills them in as the last pass
    before emission.  Seating on the recorded zero would put every machine end
    on one arbitrary corner of the machine, which is how freeform's bridge guard
    came to pass bridges the game then refused.
    """
    buildings, fresh = _bench()
    assert fresh.output_to_slot == 0, "the default a strategy leaves behind"
    assert S.emitted_sorter(fresh, buildings).output_to_slot == 7
    seat = S.seated_sorter(fresh, buildings)
    assert seat is not None
    # Slot 7 is the middle of the south face, an eighth of a tile inside the
    # tile we wrote.  Slot 0 -- the recorded default -- is its western corner,
    # four fifths of a tile away across the face.
    assert (seat.x2, seat.y2) == pytest.approx((5.0, 4.1246), abs=1e-3)
    on_slot_zero = S.slot_offset(2304, fresh.yaw, 0)
    assert abs(on_slot_zero[0]) == pytest.approx(0.7958, abs=1e-3)


def _chemical_output_sorter(
    recipe_id: int, item: str
) -> tuple[list[PlacedBuilding], PlacedBuilding]:
    machine = dataclasses.replace(_at(2309), recipe_id=recipe_id)
    belt = PlacedBuilding(
        item_id=2002,
        model_index=cat.building(2002).model_index,
        x=2,
        y=-1,
        carries_item=item,
    )
    sorter = PlacedBuilding(
        item_id=2011,
        model_index=cat.building(2011).model_index,
        x=2,
        y=1,
        x2=2,
        y2=-1,
        z2=Fraction(0),
        input_obj=0,
        output_obj=1,
        carries_item=item,
    )
    return [machine, belt], sorter


@pytest.mark.parametrize(
    ("item", "expected_filter"),
    [("graphene", 1123), ("hydrogen", 1120)],
)
def test_multi_output_machine_sorters_filter_their_exact_output(
    item: str, expected_filter: int
) -> None:
    buildings, sorter = _chemical_output_sorter(32, item)

    assert S.emitted_sorter(sorter, buildings).filter_id == expected_filter


def test_single_output_machine_sorters_remain_unfiltered() -> None:
    buildings, sorter = _chemical_output_sorter(31, "graphene")

    assert S.emitted_sorter(sorter, buildings).filter_id == 0


def test_two_sorters_meeting_on_one_belt_tile_are_not_clear() -> None:
    """The predicate both strategies ask before they take a column.

    Two ends on the same belt tile is the shape that trips the paste: both grow
    :data:`~flab2bp.dsp.colliders.SORTER_END_EXTENSION` past that tile, so they
    overlap by twice it however short the two sorters are.
    """
    buildings, into = _bench()
    buildings = [*buildings, into]
    standing = S.sorter_seat_boxes(buildings)
    assert len(standing) == 1
    meeting = PlacedBuilding(
        item_id=2011,
        model_index=cat.building(2011).model_index,
        x=5,
        y=0,
        x2=5,
        y2=2,
        z2=Fraction(0),
        input_obj=2,
        output_obj=1,
    )
    assert not S.sorter_seat_is_clear(meeting, buildings, standing)
    apart = PlacedBuilding(
        item_id=2011,
        model_index=cat.building(2011).model_index,
        x=5,
        y=-2,
        x2=5,
        y2=0,
        z2=Fraction(0),
        input_obj=3,
        output_obj=2,
    )
    assert S.sorter_seat_is_clear(apart, buildings, standing)


def test_two_columns_of_one_machine_face_are_clear_of_each_other() -> None:
    """The other half of the same rule, and the one a wrong slot gets wrong.

    Two sorters feeding one machine from adjacent columns of the same face is
    the commonest shape freeform builds, and it is legal: the paste seats their
    machine ends on the two slots they name, four fifths of a tile apart, and
    the boxes clear each other.  Seat them on the RECORDED slot instead -- which
    is zero on both until ``assign_sorter_slots`` runs -- and both ends land on
    the same pose, so the pair reads as a collision that is not there.
    """
    machine = PlacedBuilding(
        item_id=2304,
        model_index=cat.building(2304).model_index,
        x=4,
        y=4,
        width=3,
        height=3,
    )
    belts = [
        PlacedBuilding(item_id=2001, model_index=cat.building(2001).model_index, x=x, y=2)
        for x in (4, 5)
    ]

    def feeder(column: int, belt: int) -> PlacedBuilding:
        return PlacedBuilding(
            item_id=2011,
            model_index=cat.building(2011).model_index,
            x=column,
            y=2,
            x2=column,
            y2=4,
            z2=Fraction(0),
            input_obj=belt,
            output_obj=0,
        )

    standing = feeder(5, 2)
    buildings = [machine, belts[0], belts[1], standing]
    slots_named = {
        S.emitted_sorter(standing, buildings).output_to_slot,
        S.emitted_sorter(feeder(4, 1), buildings).output_to_slot,
    }
    assert len(slots_named) == 2, "adjacent columns must name different slots"
    assert S.sorter_seat_is_clear(
        feeder(4, 1), buildings, S.sorter_seat_boxes(buildings)
    )
# --- belt ports: the other array --------------------------------------------
#
# `slotPoses` in the prefab is `PrefabDesc.portPoses`, which is what a BELT is
# indexed into.  `insertPoses` in the prefab is `PrefabDesc.slotPoses`, which is
# what a SORTER is indexed into.  The names cross over and the arrays do not,
# so everything below asks the port question of the port array.


def _placed(item_id: int, x: int, y: int, yaw: float = 0.0) -> PlacedBuilding:
    w, h = cat.oriented_footprint(item_id, yaw)
    return PlacedBuilding(
        item_id=item_id,
        model_index=cat.building(item_id).model_index,
        x=x,
        y=y,
        width=w,
        height=h,
        yaw=yaw,
    )


def test_a_ray_receiver_s_ports_are_north_and_south_of_its_centre() -> None:
    """7x7 at (10, 20) has centre (13, 23); the poses are 1.122 tiles out.

    The tile NEAREST each pose is therefore inside the footprint, which is where
    the game puts the belt and what makes the collider excusals load-bearing.
    """
    docks = S.port_docks(_placed(cat.RAY_RECEIVER_ID, 10, 20))
    assert {k: d.cell for k, d in docks.items()} == {0: (13, 24), 1: (13, 22)}
    assert docks[0].facing.delta == (0, 1)
    assert docks[1].facing.delta == (0, -1)
    assert all(d.gap < 0.13 for d in docks.values()), docks


def test_a_quarter_turn_turns_the_ports_with_the_building() -> None:
    """The pose is rotated by the building's yaw, exactly as ``slot_offset`` is.

    Without it a rotated machine's ports would be read on the faces it no longer
    presents, and the dock belt would be laid a footprint away from the port it
    names.
    """
    docks = S.port_docks(_placed(cat.RAY_RECEIVER_ID, 10, 20, yaw=90.0))
    assert {k: d.cell for k, d in docks.items()} == {0: (14, 23), 1: (12, 23)}
    assert docks[0].facing.delta == (1, 0)
    assert docks[1].facing.delta == (-1, 0)


def test_an_energy_exchanger_offers_all_four_sides() -> None:
    """9x9 at the origin, centre (4, 4), poses 2.268 tiles out on each axis.

    ``temple-of-effectiveness`` puts its belts a whole tile further out than
    this -- at ``dy = +-3`` against a pose at 2.268 -- which is why
    ``rules.BELT_PORT_MAX_TILE_GAP`` is a tile rather than the 0.708 a
    nearest-tile rule can produce.
    """
    docks = S.port_docks(_placed(cat.ENERGY_EXCHANGER_ID, 0, 0))
    assert {k: d.cell for k, d in docks.items()} == {
        0: (4, 6),
        1: (6, 4),
        2: (4, 2),
        3: (2, 4),
    }
    assert all(d.gap < 0.27 for d in docks.values()), docks


def test_a_machine_with_no_port_offers_no_dock() -> None:
    """An Assembling Machine takes sorters and nothing else.

    Empty is the answer, not an exception: a planner asking what a building
    offers is a different thing from an emitter that has already wired one.
    """
    assert S.port_docks(_placed(2303, 0, 0)) == {}


def test_naming_a_port_that_does_not_exist_raises() -> None:
    """No fallback: a guessed index is what made every sorter in the first
    in-game paste invalid, and a guessed PORT index would be the same defect on
    the other array."""
    with pytest.raises(S.SlotUndetermined):
        S.port_offset(cat.RAY_RECEIVER_ID, 0.0, 2)


@pytest.mark.parametrize("name", ["12-s-purple-science-from-smelted-refined-products",
                                 "factory-heretical-smelter-block",
                                 "falk-v7-mall-full"])
def test_the_game_s_own_docks_name_the_port_this_module_computes(name: str) -> None:
    """The oracle: real blueprints, read at their RAW coordinates.

    Single-area fixtures only.  Seven of the ten store ``localOffset`` per AREA,
    so a flat read subtracts coordinates from different frames -- that is where
    every gap over one tile in the corpus comes from, and it is a property of
    the reading rather than of the game.

    What is asserted is the whole of the port model at once: the array chosen,
    the Unity-to-grid axis mapping, the yaw rotation, and the bound in
    ``rules.BELT_PORT_MAX_TILE_GAP``.  Get any of them wrong and the record the
    game wrote lands somewhere else.
    """
    text = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8").strip()
    raw = decode(text).buildings
    assert len(decode(text).areas) == 1, "a multi-area fixture cannot be read flat"
    checked = 0
    for b in raw:
        if not cat.is_belt(b.item_id):
            continue
        for peer_idx, port in (
            (b.output_obj_idx, b.output_to_slot),
            (b.input_obj_idx, b.input_from_slot),
        ):
            if not 0 <= peer_idx < len(raw):
                continue
            h = raw[peer_idx]
            try:
                info = cat.building(h.item_id)
            except KeyError:
                continue
            if not info.port_poses:
                continue
            assert 0 <= port < len(info.port_poses), (name, info.prefab, port)
            # `port_gap` wants the min corner; the fixture stores the centre.
            host = PlacedBuilding(
                item_id=h.item_id,
                model_index=h.model_index,
                x=round(h.x - (info.width - 1) / 2),
                y=round(h.y - (info.height - 1) / 2),
                width=info.width,
                height=info.height,
                yaw=h.yaw,
            )
            gap = S.port_gap(host, (round(b.x), round(b.y)), port)
            assert gap <= R.BELT_PORT_MAX_TILE_GAP, (name, info.prefab, port, gap)
            checked += 1
    assert checked >= 2, f"{name} exercised {checked} docks"


def test_assign_belt_slots_uses_the_splitter_port_facing_not_first_free() -> None:
    """A splitter slot is a physical port, not an arbitrary free pool cell."""
    belt = cat.building(2002)
    splitter = cat.building(cat.SPLITTER_ID)
    buildings = (
        PlacedBuilding(2002, belt.model_index, 1, 0, output_obj=1),
        PlacedBuilding(2002, belt.model_index, 0, 0, output_obj=2),
        PlacedBuilding(cat.SPLITTER_ID, splitter.model_index, 0, 0),
        PlacedBuilding(2002, belt.model_index, 0, 0, input_obj=2, output_obj=4),
        PlacedBuilding(2002, belt.model_index, -1, 0),
        PlacedBuilding(2002, belt.model_index, 0, 0, input_obj=2, output_obj=6),
        PlacedBuilding(2002, belt.model_index, 0, -1),
    )

    wired = S.assign_belt_slots(buildings)

    assert wired[1].output_to_slot == 1  # east port
    assert wired[3].input_from_slot == 3  # west port
    assert wired[5].input_from_slot == 2  # south port
