"""The collision model, against blueprints the game itself wrote.

A model of a game rule is worth nothing until it has been shown to (a) fire and
(b) not fire on legal input.  Both halves are here, and the second one is the
expensive half: the game cannot emit a blueprint that collides, so any real
blueprint the model flags convicts the model, not the blueprint.
"""

from __future__ import annotations

import pytest

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import colliders as C
from flab2bp.dsp.codec import decode

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
