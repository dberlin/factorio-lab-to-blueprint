"""The collision model, against blueprints the game itself wrote.

A model of a game rule is worth nothing until it has been shown to (a) fire and
(b) not fire on legal input.  Both halves are here, and the second one is the
expensive half: the game cannot emit a blueprint that collides, so any real
blueprint the model flags convicts the model, not the blueprint.
"""

from __future__ import annotations

import pathlib
from collections.abc import Sequence

import pytest

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import colliders as C
from flab2bp.dsp.codec import decode
from flab2bp.dsp.records import BlueprintBuilding

from .conftest import fixture_text

#: Fixtures the model can represent.  :func:`colliders.preview_pose` implements
#: the SINGLE-area branch of ``BlueprintUtils.RefreshBuildPreview``; a blueprint
#: split into several areas additionally goes through the tropic-anchor
#: re-basing at decompiled lines 179769-179806, which this does not.  Those
#: fixtures are therefore placed at the wrong coordinates by construction and
#: say nothing about the collision rule.  Everything the generator emits is
#: single-area, so the gap costs nothing here.
SINGLE_AREA_FIXTURES = (
    "12-s-purple-science-from-smelted-refined-products",
    "factory-heretical-smelter-block",
    "factory-quick-start-step-1-minimum-blue-cube-automation",
    "factory-quick-start-step-3-red-cube",
    "falk-v7-mall-full",
)

ASSEMBLER_MK1 = 65
SMELTER = 62
MATRIX_LAB = 70


def _pair(model: int, pitch: int, *, axis: str = "x") -> list[tuple[int, int]]:
    return C.collisions(
        [
            C.Placed(model, 0.0, 0.0, 0.0, 0.0),
            C.Placed(
                model,
                float(pitch) if axis == "x" else 0.0,
                float(pitch) if axis == "y" else 0.0,
                0.0,
                0.0,
            ),
        ]
    )


def _decoded(name: str) -> list[C.Placed]:
    """Every machine in a real blueprint, at the coordinates the game recorded.

    No rounding into tile space: the point is to test the rule against the
    numbers the game wrote, not against this repository's reading of them.
    Belts and sorters are dropped for the reasons on :func:`C.collisions`.
    """
    return [
        C.Placed(b.model_index, b.x, b.y, b.z, b.yaw)
        for b in decode(fixture_text(name)).buildings
        if not cat.is_belt(b.item_id) and not cat.is_sorter(b.item_id)
    ]


# --- the instrument can fire ------------------------------------------------


def test_grid_arc_is_not_one_world_unit() -> None:
    """The whole finding rests on this number.

    ``2 * pi / 5``, from ``GetLatitudeRadPerGrid`` and ``segment ~= radius``.  A
    footprint model that assumes 1.0 under-reserves by 25% per tile.
    """
    assert pytest.approx(1.2566370614, abs=1e-9) == C.GRID_ARC


def test_two_assemblers_three_tiles_apart_collide() -> None:
    """The defect this check exists to catch.

    ``catalog.derive_footprint`` calls an Assembling Machine 3x3, so the layout
    strategies will happily place two of them three tiles apart.  Its collider
    is 3.82 units wide and three tiles is 3.770, so the game rejects that paste
    with ``EBuildCondition.Collide``.
    """
    assert _pair(ASSEMBLER_MK1, 3)
    assert _pair(ASSEMBLER_MK1, 3, axis="y")


def test_two_assemblers_four_tiles_apart_are_clear() -> None:
    assert not _pair(ASSEMBLER_MK1, 4)
    assert not _pair(ASSEMBLER_MK1, 4, axis="y")


@pytest.mark.parametrize(
    ("model", "smallest_clear_pitch"),
    [
        # Each is the spacing the corpus actually uses and never goes below:
        # smelters appear at 3, assemblers only ever at 4 or more, Matrix Labs
        # only ever at 5 or more.  Measured over every fixture.
        (SMELTER, 3),
        (ASSEMBLER_MK1, 4),
        (MATRIX_LAB, 5),
    ],
)
def test_minimum_clear_pitch_matches_the_corpus(model: int, smallest_clear_pitch: int) -> None:
    assert _pair(model, smallest_clear_pitch - 1), "one tile tighter must collide"
    assert not _pair(model, smallest_clear_pitch), "the corpus spacing must be clear"


def test_clearance_turns_with_the_building() -> None:
    """A collider is a box with a rotation, not a square.

    A Spray Coater's tested box is 0.7 x 3.5 world units, so two of them one
    tile apart in y collide when they face north and are clear when they face
    west.  ``factory-heretical-smelter-block`` has five at yaw 270 stacked at
    y = 16, 17, 18 -- one tile apart, which only works because of the rotation.
    Reading a footprint as a square would call that a collision and convict a
    blueprint the game wrote.
    """
    north = [C.Placed(120, 0.0, 0.0, 0.0, 0.0), C.Placed(120, 0.0, 1.0, 0.0, 0.0)]
    west = [C.Placed(120, 0.0, 0.0, 0.0, 270.0), C.Placed(120, 0.0, 1.0, 0.0, 270.0)]
    assert C.collisions(north)
    assert not C.collisions(west)


def test_a_model_with_no_build_collider_is_never_reported() -> None:
    """``hasBuildCollider == false`` makes the game skip the test entirely.

    Two copies of such a prefab stacked at the same coordinates must still come
    back clean, or the model is inventing collisions the game cannot raise.
    """
    missing = 999999
    assert C.build_colliders(missing) == ()
    assert not C.collisions([C.Placed(missing, 0.0, 0.0, 0.0, 0.0)] * 2)


def test_the_flat_model_is_the_permissive_one() -> None:
    """Why an error-level check may use it.

    Columns compress by ``cos(lat)`` away from the anchor, so a real paste can
    only ever be tighter than the flat grid, never looser.  Five Matrix Labs on
    a five-tile pitch are the cleanest demonstration: clear flat and clear at
    the equator, but colliding once the row sits far enough north.
    """
    labs = [C.Placed(MATRIX_LAB, float(5 * i), 81.0, 0.0, 0.0) for i in range(5)]
    assert not C.collisions(labs)
    assert not C.collisions(labs, anchor_lat=-81.0 * 2.0 * 3.141592653589793 / 1000.0)
    assert C.collisions(labs, anchor_lat=0.0)


# --- and does not fire on what the game wrote -------------------------------


@pytest.mark.parametrize("name", SINGLE_AREA_FIXTURES)
def test_real_blueprints_have_no_collisions(name: str) -> None:
    placed = _decoded(name)
    assert placed, "fixture decoded to nothing"
    hits = C.collisions(placed)
    assert not hits, [
        (placed[a].model_index, placed[a].x, placed[a].y)
        + (placed[b].model_index, placed[b].x, placed[b].y)
        for a, b in hits[:5]
    ]


@pytest.mark.parametrize("name", SINGLE_AREA_FIXTURES)
def test_the_negative_control_is_not_vacuous(name: str) -> None:
    """Guards the guard.

    A control made of nothing but 1x1 towers would pass while testing nothing.
    Each fixture must contribute several machines with real build colliders, or
    "zero collisions" is not evidence.
    """
    placed = _decoded(name)
    with_colliders = [p for p in placed if C.build_colliders(p.model_index)]
    assert len(with_colliders) >= 5
    assert len({p.model_index for p in with_colliders}) >= 2


def test_the_control_would_notice_a_shifted_building() -> None:
    """The fixtures are not so sparse that nothing could ever collide in them.

    Sliding every machine in the densest fixture one tile along must break it.
    If it does not, the fixture has too much slack to be a control at all.
    """
    placed = _decoded("12-s-purple-science-from-smelted-refined-products")
    assert not C.collisions(placed)
    nudged = [
        C.Placed(p.model_index, p.x + (1.0 if i % 2 else 0.0), p.y, p.z, p.yaw)
        for i, p in enumerate(placed)
    ]
    assert C.collisions(nudged)


# --- the belt crossing rule -------------------------------------------------
#
# A belt is not box-tested.  `CheckBuildConditions` line 145761 probes it with a
# 0.23 sphere centred 0.2 above the node, and line 145872 excuses a machine
# against a belt but not a belt against a machine.  So a belt MAY cross a
# building, and the question is only how high.

_ASSEMBLER_2 = 66
_ARC_SMELTER = 62
_SPLITTER = 38
_TESLA_TOWER = 44
_BELT_MK3 = 37
_SORTER_3 = 43


def test_belt_crossing_height_is_the_collider_top_plus_the_probe_reach() -> None:
    """`z > (top + RADIUS - LIFT) * 3/4`, arithmetic held to the data.

    An Assembling Machine's build collider tops out at 4.68 model units and the
    probe reaches 0.03 BELOW the belt node, so the belt must stand at
    `(4.68 + 0.03) * 3/4 = 3.5325` -- four half-levels, not one.  Fixing the
    numbers here is what makes the constants mutation-visible: change either of
    them and this fails.
    """
    assert C.BELT_PROBE_RADIUS == 0.23
    assert C.BELT_PROBE_LIFT == 0.2
    assert C.belt_crossing_height(_ASSEMBLER_2) == pytest.approx(3.5325)
    assert C.belt_crossing_height(_ARC_SMELTER) == pytest.approx(2.7975)
    assert C.belt_crossing_height(_SPLITTER) == pytest.approx(1.7475)
    assert C.belt_crossing_height(_SORTER_3) == pytest.approx(0.7575)


def test_a_belt_crosses_an_assembler_only_above_that_height() -> None:
    """The bound is tight from both sides, on the belt's own half-level grid."""
    machine = [C.Placed(_ASSEMBLER_2, 0.0, 0.0, 0.0, 0.0)]
    for z in (0.0, 1.0, 2.0, 3.0, 3.5):
        assert C.belt_crossings([C.Placed(_BELT_MK3, 0.0, 0.0, z, 0.0)], machine), z
    assert not C.belt_crossings([C.Placed(_BELT_MK3, 0.0, 0.0, 4.0, 0.0)], machine)
    # And the boundary itself: just under the computed height collides, just
    # over it does not.
    h = C.belt_crossing_height(_ASSEMBLER_2)
    assert C.belt_crossings([C.Placed(_BELT_MK3, 0.0, 0.0, h - 0.01, 0.0)], machine)
    assert not C.belt_crossings([C.Placed(_BELT_MK3, 0.0, 0.0, h + 0.01, 0.0)], machine)


def test_the_belt_probe_is_a_sphere_and_not_the_belt_box() -> None:
    """Two tiles from an assembler is clear at ground level.

    The probe is 0.23, so it must clear a 1.91-unit collider by 2.14 units --
    1.71 tiles.  A box model of the belt would put the boundary somewhere else,
    and the footprint model puts it at two tiles for a different reason.
    """
    machine = [C.Placed(_ASSEMBLER_2, 0.0, 0.0, 0.0, 0.0)]
    assert C.belt_crossings([C.Placed(_BELT_MK3, 1.0, 0.0, 0.0, 0.0)], machine)
    assert not C.belt_crossings([C.Placed(_BELT_MK3, 2.0, 0.0, 0.0, 0.0)], machine)


def test_a_splitter_is_not_a_belt_and_is_box_tested() -> None:
    """`isBelt = beltSpeed > 0`; a Splitter sets `isSplitter` instead.

    Both of the open collider questions turn on this.  A Splitter one tile from
    a Tesla Tower collides because 1.19 + 0.30 exceeds one 1.2566-unit tile --
    a plain pitch requirement, nothing to do with crossing.  And an elevated
    Splitter over an Assembling Machine is box against box: it needs the same
    height a belt would, but for the box reason, and three tiles of separation
    clears it at any height.
    """
    tower = C.Placed(_TESLA_TOWER, 0.0, 0.0, 0.0, 0.0)
    assert C.collisions([C.Placed(_SPLITTER, 1.0, 0.0, 0.0, 0.0), tower])
    assert not C.collisions([C.Placed(_SPLITTER, 2.0, 0.0, 0.0, 0.0), tower])

    machine = C.Placed(_ASSEMBLER_2, 0.0, 0.0, 0.0, 0.0)
    assert C.collisions([machine, C.Placed(_SPLITTER, 1.0, 1.0, 1.0, 0.0)])
    assert not C.collisions([machine, C.Placed(_SPLITTER, 1.0, 1.0, 4.0, 0.0)])
    assert not C.collisions([machine, C.Placed(_SPLITTER, 3.0, 3.0, 1.0, 0.0)])


def test_real_blueprints_fly_belts_over_buildings_and_always_clear_them() -> None:
    """The rule fires and does not misfire, on blueprints the game wrote.

    Over the single-area fixtures, take every belt whose probe sits inside a
    collider's footprint while standing higher than that building.  Each one
    must CLEAR the collider, unless the building is one the game lets things
    stack on (``multiLevel`` -- a belt a level above a Splitter or a Storage
    Tank is on its upper port, not crossing it) or one of
    ``catalog.LOW_CONFIDENCE_FOOTPRINTS``, whose colliders are already recorded
    as not reproducing real blueprints.

    If the height bound were too high these real belts would be convicted; if it
    were too low nothing would be counted as clearing at all.
    """
    clear = 0
    for name in SINGLE_AREA_FIXTURES:
        raw = decode(fixture_text(name)).buildings
        belts = [
            C.Placed(b.model_index, b.x, b.y, b.z, b.yaw)
            for b in raw
            if cat.is_belt(b.item_id)
        ]
        others = [
            (b, C.Placed(b.model_index, b.x, b.y, b.z, b.yaw))
            for b in raw
            if not cat.is_belt(b.item_id)
            and not cat.is_sorter(b.item_id)
            and C.build_colliders(b.model_index)
        ]
        for belt in belts:
            probe = C.belt_probe(belt.x, belt.y, belt.z)
            for src, other in others:
                if belt.z <= other.z or abs(other.x - belt.x) > 8 or abs(other.y - belt.y) > 8:
                    continue
                pose = C.flat_pose(other.x, other.y, other.z, other.yaw)
                if not any(
                    C.probe_inside_footprint(probe, box)
                    for box in C.target_boxes(other, *pose)
                ):
                    continue
                if not C.belt_crossings([belt], [other], directly_over_only=True):
                    clear += 1
                    continue
                try:
                    info = cat.building(src.item_id)
                except KeyError:  # not a catalog building; nothing to assert
                    continue
                assert info.multi_level or src.item_id in cat.LOW_CONFIDENCE_FOOTPRINTS, (
                    f"{info.name} in {name}: a belt at z={belt.z} stands over its "
                    f"collider without clearing it"
                )
    assert clear >= 20, clear


# --- the lateral half: the excusal, and what it must and must not let through


def _previews(name: str) -> list[C.Preview]:
    """A fixture as the paste sees it, at the coordinates the game recorded.

    No rounding into tile space.  `tests/layout/test_validate.py` asks the same
    question of a `Placement`, which HAS been rounded; only this one is a test
    of the rule rather than of the rounding.
    """
    raw = decode(fixture_text(name)).buildings
    return [
        C.Preview(
            b.model_index,
            b.x,
            b.y,
            float(b.z),
            b.yaw,
            is_belt=cat.is_belt(b.item_id),
            is_inserter=cat.is_sorter(b.item_id),
            is_splitter=b.item_id == cat.SPLITTER_ID,
            is_belt_addon=_is_addon(b.item_id),
            output=b.output_obj_idx if b.output_obj_idx >= 0 else None,
            input=b.input_obj_idx if b.input_obj_idx >= 0 else None,
        )
        for b in raw
    ]


def _is_addon(item_id: int) -> bool:
    try:
        return cat.building(item_id).is_belt_addon
    except KeyError:
        return False


@pytest.mark.parametrize("name", SINGLE_AREA_FIXTURES)
def test_the_excused_verdict_convicts_no_belt_the_game_itself_placed(name: str) -> None:
    """The negative control the lateral half was blocked on.

    Raw, the 0.23 probe flags 1189 belts across the fixture corpus in blueprints
    the game wrote.  With the paste's own excusals -- three belt hops either way
    to the building the run reaches, a Splitter's linked previews, and a run that
    ends in a building -- it must flag none.  That is the whole claim, and this
    is what would falsify it.
    """
    previews = _previews(name)
    hits = C.belt_collisions(previews)
    named = [
        (i, j, cat.building(decode(fixture_text(name)).buildings[j].item_id).name)
        for i, j in hits[:5]
    ]
    assert not hits, named


def test_the_excusal_is_what_makes_the_corpus_clean_not_the_geometry() -> None:
    """Mutation control: break the excusal and the same fixtures convict.

    Without this the test above could pass because nothing overlaps at all.  It
    is the one fixture with Splitters in it, and every belt beside one of them
    grazes its 1.19-unit arm by 0.16 of the 0.23 probe.
    """
    previews = _previews("factory-quick-start-step-3-red-cube")
    assert not C.belt_collisions(previews)
    stripped = [
        C.Preview(
            p.model_index,
            p.x,
            p.y,
            p.z,
            p.yaw,
            is_belt=p.is_belt,
            is_inserter=p.is_inserter,
            is_splitter=p.is_splitter,
            is_belt_addon=p.is_belt_addon,
        )
        for p in previews
    ]
    assert len(C.belt_collisions(stripped)) >= 20


def test_a_belt_is_excused_three_hops_from_what_its_run_reaches_and_no_further() -> None:
    """`CheckBuildConditions` 147451, at its exact reach.

    Only the four tiles orthogonally adjacent to a Splitter graze its 1.19-unit
    arm, so the run is bent into a U to put a THIRD one of them four hops down
    the chain.  Belt 1 touches the splitter and outputs into it; belt 3 reaches
    it on the third hop and is excused; belt 5 reaches it on the fifth and is
    not.  Belts 2 and 4 sit on the diagonal, 0.635 units clear, and are not hits
    at all -- which is what makes the difference between 3 and 5 the excusal's
    and not the geometry's.
    """
    where = {1: (1, 0), 2: (1, 1), 3: (0, 1), 4: (-1, 1), 5: (-1, 0)}
    previews = [C.Preview(_SPLITTER, 0.0, 0.0, 0.0, is_splitter=True)]
    for n, (x, y) in where.items():
        previews.append(
            C.Preview(_BELT_MK3, float(x), float(y), 0.0, is_belt=True, output=n - 1)
        )
    assert C.belt_collisions(previews) == [(5, 0)]

    # Every one of the three that touches it is a hit without the links: that is
    # what the chain is doing, and 1 and 3 are not simply out of range.
    stripped = [
        C.Preview(
            p.model_index, p.x, p.y, p.z, is_belt=p.is_belt, is_splitter=p.is_splitter
        )
        for p in previews
    ]
    assert C.belt_collisions(stripped) == [(1, 0), (3, 0), (5, 0)]


def test_a_belt_beside_a_machine_it_has_nothing_to_do_with_still_collides() -> None:
    """The rule must not have been widened into a licence."""
    assert C.belt_collisions(
        [
            C.Preview(_ASSEMBLER_2, 0.0, 0.0, 0.0),
            C.Preview(_BELT_MK3, 1.0, 0.0, 0.0, is_belt=True),
        ]
    ) == [(1, 0)]
    # ... and one hop away it is excused, which is the clause at 147492.
    assert not C.belt_collisions(
        [
            C.Preview(_ASSEMBLER_2, 0.0, 0.0, 0.0),
            C.Preview(_BELT_MK3, 1.0, 0.0, 0.0, is_belt=True, output=0),
        ]
    )


def test_a_raw_sorter_box_test_convicts_blueprints_the_game_wrote() -> None:
    """Why :func:`C.collisions` still says nothing about sorter-on-sorter.

    The reason recorded in that docstring used to be the slot data, and that
    reason expired when the real ``PrefabDesc.slotPoses`` were extracted from
    the prefabs.  The live reason is the RE-SEATING: the game rebuilds a
    sorter's collider onto the poses of the buildings it connects
    (``RefreshBuildPreview`` 180039-180096), so testing the prefab box where the
    blueprint record puts it is not the game's test.

    Both halves are asserted, because either alone would let the docstring drift
    back:

    * the slot data is THERE now -- an Assembling Machine has twelve poses -- so
      "we cannot, the data is wrong" is no longer available as an excuse;
    * and the raw box test is refuted by the corpus: the game's own blueprints
      put sorter anchors closer than the box is wide, 53 times over 1132
      sorters, in pastes that work.  A port that raised those would be wrong.

    The count is asserted as a floor rather than an equality: the claim is that
    the raw test convicts real blueprints, and one more fixture must not turn a
    reinforcement of that claim into a failure.
    """
    assert len(cat.building(2303).slot_poses) == 12, "the extraction landed"

    radius = 0.26
    anchors: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    close = 0
    duplicated = 0
    # PER BLUEPRINT, not pooled: two fixtures are two separate pastes, and their
    # coordinates are both local to their own anchor.  Pooling them invents
    # pairs -- it reported two shared points that are simply the same offset in
    # two different blueprints.
    for name in SINGLE_AREA_FIXTURES:
        here = [
            ((b.x, b.y, b.z), (b.x2, b.y2, b.z2))
            for b in decode(fixture_text(name)).buildings
            if cat.is_sorter(b.item_id)
        ]
        anchors += here
        shared: dict[tuple[float, float, float], int] = {}
        for ends in here:
            for end in ends:
                key = (round(end[0], 3), round(end[1], 3), round(end[2], 3))
                shared[key] = shared.get(key, 0) + 1
        duplicated += sum(1 for v in shared.values() if v > 1)
        for i, a in enumerate(here):
            for b2 in here[i + 1 :]:
                if min(
                    sum((u[k] - v[k]) ** 2 for k in range(3)) ** 0.5
                    for u in a
                    for v in b2
                ) < 2 * radius:
                    close += 1

    assert len(anchors) == 1132, "the sample is the whole single-area corpus"

    # The game never puts two sorter anchors on the same point.  We do -- 172 of
    # them over 702 emitted sorters -- which is the measurement the backlog entry
    # carries; it is recorded there rather than asserted here, because this test
    # is about the GAME's geometry.
    assert duplicated == 0

    assert close >= 53, (
        f"only {close} pairs under {2 * radius} units; if this ever reaches 0 the "
        "raw box test is no longer refuted and the sorter check can be ported"
    )

def test_the_splitter_keep_out_is_the_plus_shape_and_one_level_up() -> None:
    """`belt_keepout_offsets`, against the rule read off the C#.

    The four orthogonal neighbours and the tile itself, at ``dz`` 0 and 1.  Both
    bounds matter and both are the collider's:

    * laterally, the arms reach 1.19 units and the probe 0.23, against a
      1.2566-unit tile -- so one tile out grazes at 1.2566 < 1.42 and the
      DIAGONAL at 1.777 does not;
    * vertically, the cross stands 2.30 units and a blueprint level is 4/3, so a
      belt one level up sits inside it and two levels up clears.

    A caller that keeps foreign belts out of exactly these cells cannot be
    convicted by `belt_collisions`, which is what the freeform router uses it
    for.
    """
    got = C.belt_keepout_offsets(_SPLITTER)
    assert got == frozenset(
        {(dx, dy, dz) for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
         for dz in (0, 1)}
    ), sorted(got)


def test_the_keep_out_agrees_with_the_verdict_it_is_derived_from() -> None:
    """Not a second opinion: every offset in it really does convict.

    The falsifier is the pairing.  An offset the set names where an unlinked
    belt is NOT convicted would make it over-strict, and one it leaves out where
    a belt IS convicted would make it unsound -- so both directions are checked
    over the whole search box rather than the answer being restated.
    """
    keep = C.belt_keepout_offsets(_SPLITTER)
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            for dz in range(-1, 3):
                hits = C.belt_collisions(
                    [
                        C.Preview(_SPLITTER, 0.0, 0.0, 0.0, is_splitter=True),
                        C.Preview(
                            _BELT_MK3, float(dx), float(dy), float(dz), is_belt=True
                        ),
                    ]
                )
                assert bool(hits) == ((dx, dy, dz) in keep), (dx, dy, dz, hits)


# --- sorter on sorter -------------------------------------------------------
#
# The one pairing the paste's excusal does not forgive.  See
# ``colliders.sorter_collisions`` for the C# and for why this is the ONLY
# collision a sorter can score.

#: The blueprint the user pasted and the game refused with "Collide with other
#: object", drawn red on exactly two clusters.  It is a fixture rather than a
#: regenerated case because CP-SAT does not reproduce it on demand: six straight
#: regenerations of the same spec did not.
#:
#: It lives under ``fixtures/ours/`` and NOT beside the game's blueprints, and
#: that separation is load-bearing: everything in ``fixtures/`` is evidence
#: about what the GAME does, and several tests derive corpus-wide statements by
#: globbing that directory.  A blueprint we wrote -- an INVALID one, at that --
#: standing in that sample would corrupt every one of them.
_OURS = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "ours"
FAILING_PASTE = _OURS / "sorter-collide-freeform.txt"

#: What the GAME actually built from it, blueprinted back out of the save.
#: 347 buildings against our 352: every belt and every machine, and 33 of
#: the 38 sorters.  The five it dropped are the answer key.
BUILT_RESULT = _OURS / "sorter-collide-built.txt"

#: The built blueprint was copied at a different rotation and anchor.  The
#: transform is exact and was solved against all 17 machines:
#: a quarter turn, then a translation.  Buildings are also REORDERED, so
#: nothing may be matched by index.
def _as_built(x: float, y: float) -> tuple[float, float]:
    return (y + 3.0, -x + 27.0)


def _sorter_previews(
    buildings: Sequence[BlueprintBuilding],
) -> list[tuple[int, C.SorterPreview]]:
    """Every sorter in a decoded blueprint, as the paste's collision test sees it.

    A blueprint the GAME wrote already carries seated ends -- it recorded what it
    built, and what it built is where ``RefreshBuildPreview`` put it -- so no
    seating is applied here.  ``validate.game.sorter_collide`` seats, because
    what WE emit is a tile centre and the paste moves it.
    """
    by_index = {b.index: b for b in buildings}

    def is_open(idx: int) -> bool:
        other = by_index.get(idx)
        return other is None or cat.is_belt(other.item_id)

    return [
        (
            b.index,
            C.SorterPreview(
                cat.building(b.item_id).model_index,
                b.x, b.y, b.z, b.x2, b.y2, b.z2,
                is_open(b.input_obj_idx),
                is_open(b.output_obj_idx),
            ),
        )
        for b in buildings
        if cat.is_sorter(b.item_id)
    ]


def test_sorter_collisions_are_absent_from_the_games_own_blueprints() -> None:
    """The counter-measurement, and the proof that it is not vacuous.

    Zero pairs over the whole single-area corpus.  A sample that could not have
    shown otherwise would be worthless, so the two shapes a coarser rule WOULD
    have banned are counted here as well: the same 1132 sorters overlap one
    another's plan tiles 53 times and include belt-to-belt sorters.  Both are
    legal, both are common, and both survive this predicate untouched -- what
    separates them from the failing paste is the box, not the topology.
    """
    total = shared_tiles = belt_to_belt = hits = 0
    for name in SINGLE_AREA_FIXTURES:
        buildings = decode(fixture_text(name)).buildings
        by_index = {b.index: b for b in buildings}
        previews = _sorter_previews(buildings)
        total += len(previews)
        hits += len(C.sorter_collisions([p for _i, p in previews]))

        sorters = [b for b in buildings if cat.is_sorter(b.item_id)]
        for b in sorters:
            src, dst = by_index.get(b.input_obj_idx), by_index.get(b.output_obj_idx)
            if src is not None and dst is not None:
                belt_to_belt += cat.is_belt(src.item_id) and cat.is_belt(dst.item_id)

        def body(b: BlueprintBuilding) -> set[tuple[int, int]]:
            x1, y1 = round(b.x), round(b.y)
            x2, y2 = round(b.x2), round(b.y2)
            steps = max(abs(x2 - x1), abs(y2 - y1)) or 1
            return {
                (x1 + (x2 - x1) * k // steps, y1 + (y2 - y1) * k // steps)
                for k in range(steps + 1)
            }

        bodies = [body(b) for b in sorters]
        for i in range(len(bodies)):
            for j in range(i + 1, len(bodies)):
                shared_tiles += bool(bodies[i] & bodies[j])

    assert total == 1132, "the sample is the whole single-area corpus"
    assert shared_tiles >= 53, "sorter bodies DO share tiles in blueprints that paste"
    assert belt_to_belt >= 4, "belt-to-belt sorters ARE legal"
    assert hits == 0


def test_the_paste_the_game_refused_is_convicted() -> None:
    """The positive half, against the game's own verdict on a real paste.

    The user pasted this blueprint and the game drew two red clusters, naming
    ``Collide with other object``.  Those clusters are sorters 46/163 and
    21/55/162, and this predicate names all three pairs and nothing else out of
    38 sorters.
    """
    previews = _sorter_previews(
        decode(FAILING_PASTE.read_text(encoding="utf-8")).buildings
    )
    named = [
        (previews[i][0], previews[j][0])
        for i, j in C.sorter_collisions([p for _i, p in previews])
    ]
    assert len(previews) == 38
    assert named == [(21, 162), (46, 163), (55, 162)]


def _straight(span: float, offset: float, *, open_ends: bool) -> C.SorterPreview:
    """A sorter running north from ``(offset, 0)``, ``span`` tiles long."""
    return C.SorterPreview(
        41, offset, 0.0, 0.0, offset, span, 0.0, open_ends, open_ends
    )


def test_the_sorter_box_spans_its_two_ends_and_not_its_record() -> None:
    """The stretch is the rule; a prefab box at the anchor would say otherwise.

    Two collinear sorters that meet head to tail at a shared tile collide -- that
    is the failing paste's shape.  The same two moved four tiles apart do not.
    A model that tested the 0.115-deep prefab box where the record sits would
    report neither.
    """
    meeting = [_straight(2.0, 0.0, open_ends=True)] + [
        C.SorterPreview(41, 0.0, 2.0, 0.0, 0.0, 4.0, 0.0, True, True)
    ]
    assert C.sorter_collisions(meeting) == [(0, 1)]

    apart = [_straight(2.0, 0.0, open_ends=True)] + [
        C.SorterPreview(41, 0.0, 6.0, 0.0, 0.0, 8.0, 0.0, True, True)
    ]
    assert C.sorter_collisions(apart) == []


def test_an_end_that_meets_a_machine_does_not_extend() -> None:
    """``SORTER_END_EXTENSION`` applies to a belt end or an open end, not a machine.

    Two one-tile sorters whose facing ends are 0.4 of a tile apart clear each
    other when both are seated on machines, and collide when both are belt or
    open ends -- 0.35 units of growth on each of the four ends is 1.4 units
    against the 0.503 that separates them.  That asymmetry is the
    ``ObjectIsBelt`` / ``inputObjId == 0 && input == null`` branch pair, and it
    is what makes a belt-to-belt hop so much wider than its span.
    """
    closed = [
        C.SorterPreview(41, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, False, False),
        C.SorterPreview(41, 0.0, 1.4, 0.0, 0.0, 2.4, 0.0, False, False),
    ]
    assert C.sorter_collisions(closed) == []
    opened = [
        C.SorterPreview(41, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, True, True),
        C.SorterPreview(41, 0.0, 1.4, 0.0, 0.0, 2.4, 0.0, True, True),
    ]
    assert C.sorter_collisions(opened) == [(0, 1)]


def test_the_check_names_exactly_the_sorters_the_game_refused_to_build() -> None:
    """The answer key, from the game itself.

    The user force-built the refused paste and blueprinted the result back out.
    The game created every one of the 297 belts and all 17 machines, and 33 of
    the 38 sorters.  It dropped five, and this is the whole labelled sample:
    five positives and thirty-three negatives, decided by the game rather than
    by anyone's reading of it.

    The five it dropped are named here by matching each of our sorters against
    the built blueprint through :func:`_as_built`, on BOTH ends and with a
    tolerance of 0.8 tiles -- the built ends carry the paste seating, which moved
    32 of the 33 survivors by 0.57 to 1.22 units.

    This predicate names those five and no others.  It is not a fit to them: it
    is ``EBuildCondition.Collide``'s own box, and the same predicate is silent
    on all 1132 sorters of the single-area fixture corpus and on the 33 sorters
    the game did build here.
    """
    ours = decode(FAILING_PASTE.read_text(encoding="utf-8")).buildings
    built = [
        b
        for b in decode(BUILT_RESULT.read_text(encoding="utf-8")).buildings
        if cat.is_sorter(b.item_id)
    ]
    assert len(built) == 33

    refused = set()
    for b in (s for s in ours if cat.is_sorter(s.item_id)):
        head, tail = _as_built(b.x, b.y), _as_built(b.x2, b.y2)
        if not any(
            max(
                abs(c.x - head[0]),
                abs(c.y - head[1]),
                abs(c.x2 - tail[0]),
                abs(c.y2 - tail[1]),
            )
            < 0.8
            for c in built
        ):
            refused.add(b.index)
    assert refused == {21, 46, 55, 162, 163}, "the game's own verdict"

    previews = _sorter_previews(ours)
    convicted = {
        previews[k][0]
        for pair in C.sorter_collisions([p for _i, p in previews])
        for k in pair
    }
    assert convicted == refused


def test_what_the_game_actually_built_is_clean() -> None:
    """The negative control with the seating baked in, by the game.

    Every end in the built blueprint is where ``RefreshBuildPreview`` put it,
    not where we asked.  If the predicate were an artefact of testing unseated
    tile centres it would still fire here; it does not.
    """
    previews = _sorter_previews(decode(BUILT_RESULT.read_text(encoding="utf-8")).buildings)
    assert len(previews) == 33
    assert C.sorter_collisions([p for _i, p in previews]) == []
