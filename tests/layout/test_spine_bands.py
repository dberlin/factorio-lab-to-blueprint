"""Spine's layouts, checked where the game will actually paste them.

The flat model in ``dsp.colliders`` is the equatorial supremum, so a layout that
clears ``geom.collide`` and ``game.inserter_skew`` can still be refused.  These
tests pin the two things that changed when the band model arrived: the packer no
longer emits a machine-to-machine insert the game calls ``TooClose``, and every
layout it does emit is verified against the game's own predicates at every
anchor of the band it declares.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import codec, colliders, planet
from flab2bp.layout import spine
from flab2bp.layout.base import DETERMINISTIC_WORKERS, PlacedBuilding, Placement
from flab2bp.spec import BuildSpec

from .test_spine import single_recipe_spec, two_stage_spec

SEG = colliders.PLANET_SEGMENT


@pytest.fixture(scope="module")
def two_stage_placement() -> Placement:
    return spine.SpineLayout(power=True, workers=DETERMINISTIC_WORKERS).lay_out(
        two_stage_spec(), time_budget_s=20.0
    )


def test_no_machine_to_machine_sorter_is_under_the_games_floor(
    two_stage_placement: Placement,
) -> None:
    """The regression.  Before ``MIN_DIRECT_INSERT_GAP`` this was 1.329.

    A sorter with neither end on a belt must reach at least
    ``SORTER_COMBINED_MIN[0]`` = 1.451 GRID CELLS, or the paste reports
    ``TooClose`` (``num134``, ``BuildTool_BlueprintPaste.cs:3459``).  The packer
    used to allow a one-tile gap between a direct-insert pair, which seats the
    sorter at 1.329 cells -- legal on every flat test we had, and refused by the
    game.

    The evidence that 1.451 is real rather than a misread: of the 48
    machine-to-machine sorters in the single-area blueprints the GAME wrote, the
    shortest reaches 2.249 cells and not one is under the floor.
    """
    band = planet.bands(SEG)[0]
    projection = planet.Projection(
        band=band, anchor_row=0, segment=SEG, radius=colliders.PLANET_RADIUS
    )
    machine_to_machine = [
        s for s in spine._band_sorters(two_stage_placement) if s.belt_ends == 0
    ]
    for sorter in machine_to_machine:
        a = projection.position(sorter.x, sorter.y, sorter.z)
        b = projection.position(sorter.x2, sorter.y2, sorter.z2)
        r = projection.position(sorter.ref_x, sorter.ref_y, sorter.ref_z)
        across = planet.calc_segments_across(r, a, b, SEG)
        assert across >= planet.SORTER_COMBINED_MIN[0], (
            f"machine-to-machine sorter reaches {across:.3f} cells, under the "
            f"{planet.SORTER_COMBINED_MIN[0]} the game allows"
        )


@pytest.mark.parametrize("factory", [single_recipe_spec, two_stage_spec], ids=lambda f: f.__name__)
def test_every_layout_pastes_at_every_anchor_of_the_band_it_declares(
    factory: Callable[[], BuildSpec],
) -> None:
    """``lay_out`` promises a layout the GAME accepts, not one our flat model does.

    The promise is per band and per anchor: take the band the placement records,
    walk every anchor it offers in both quadrants, project, and run the game's
    own collision and sorter predicates.  Nothing may convict.
    """
    placement = spine.SpineLayout(power=True, workers=DETERMINISTIC_WORKERS).lay_out(
        factory(), time_budget_s=20.0
    )
    assert spine._band_rejected(placement) == ""
    declared = placement.stats.get("area_segments")
    assert declared is not None, "lay_out must record the band it verified"

    band = next(b for b in planet.bands(SEG) if b.area_segments == int(declared))
    min_x, min_y, max_x, max_y = placement.bounds
    rotated = bool(placement.stats.get("band_rotated", 0.0))
    width, height = max_x - min_x + 1, max_y - min_y + 1
    rows, cols = (width, height) if rotated else (height, width)
    assert rows <= band.rows and cols <= band.columns

    # And the area record carries it, rather than the old hardcoded 200.
    area = codec.placement_to_blueprint(placement).areas[0]
    assert area.area_segments == int(declared)


def test_the_declared_band_is_one_area_by_the_games_own_count() -> None:
    """Whatever band is declared, ``GetAreaCount`` must call the extent one area.

    This is the ``BlueprintAreaCrossTropic`` predicate itself, so it is the
    difference between a blueprint that pastes and one the game draws red.
    """
    placement = spine.SpineLayout(power=True, workers=DETERMINISTIC_WORKERS).lay_out(
        two_stage_spec(), time_budget_s=20.0
    )
    declared = int(placement.stats["area_segments"])
    band = next(b for b in planet.bands(SEG) if b.area_segments == declared)
    min_x, min_y, max_x, max_y = placement.bounds
    rotated = bool(placement.stats.get("band_rotated", 0.0))
    rows = (max_x - min_x + 1) if rotated else (max_y - min_y + 1)
    anchors = band.anchors(rows)
    assert anchors, f"band {declared} offers no anchor for {rows} rows"
    for anchor in anchors:
        assert planet.area_count(anchor, anchor + rows - 1, SEG) == 1


def test_the_gate_can_convict_so_a_pass_means_something() -> None:
    """A gate that cannot fail is not a gate.

    Two things have to be shown, because ``_band_rejected`` answers a question
    with two ways of coming out clean.

    First that a BAND can convict: two Matrix Labs five columns apart clear the
    flat model, and at the poleward edge of the equatorial band they collide.
    That is the exact case ``colliders``' own docstring describes and cannot
    check.

    Second that the SEARCH can run out: a layout too tall for the equatorial band
    fits no band at all, and the gate says ``band.cross_tropic`` rather than
    quietly declaring 200 the way the encoder used to.
    """
    lab = 2901
    b = cat.building(lab)
    pair = [
        colliders.Placed(b.model_index, 0.0, 0.0, 0.0, 0.0),
        colliders.Placed(b.model_index, 5.0, 0.0, 0.0, 0.0),
    ]
    band = planet.bands(SEG)[0]
    fit = planet.Fit(band=band, rotated=False, rows=5, columns=10)
    assert colliders.collisions(pair) == []  # flat says clean
    assert spine._band_illegal(pair, [], fit, SEG, colliders.PLANET_RADIUS) == {"band.collide"}

    # Over 161 rows in BOTH directions fits nowhere on the planet.  It has to be
    # both: 205x5 is far too tall upright and slots into the 60-segment band
    # turned sideways, which is the whole reason `band_for_extent` considers the
    # quarter turn.
    assert spine._band_rejected(_two_labs(0, 200)) == ""  # fits turned
    assert spine._band_rejected(_two_labs(200, 200)).startswith("band.cross_tropic")


def _two_labs(dx: int, dy: int) -> Placement:
    b = cat.building(2901)
    return Placement(
        buildings=(
            PlacedBuilding(2901, b.model_index, 0, 0, Fraction(0), b.width, b.height, 0.0),
            PlacedBuilding(2901, b.model_index, dx, dy, Fraction(0), b.width, b.height, 0.0),
        )
    )


def test_a_four_cell_sorter_is_convicted_even_though_its_length_passes() -> None:
    """The clause ``dsp.rules`` declined to port, exercised end to end."""
    band = planet.bands(SEG)[0]
    projection = planet.Projection(
        band=band, anchor_row=0, segment=SEG, radius=colliders.PLANET_RADIUS
    )
    sorter = planet.Sorter(
        x=0.0, y=0.0, z=0.0, x2=0.0, y2=4.0, z2=0.0, yaw=0.0, yaw2=0.0,
        input_belt=False, output_belt=False, ref_x=0.0, ref_y=2.0, ref_z=0.0,
    )
    world = math.dist(
        projection.position(sorter.x, sorter.y, sorter.z),
        projection.position(sorter.x2, sorter.y2, sorter.z2),
    )
    assert world < 7.5  # inside rules.SORTER_LENGTH[0]
    assert planet.sorter_condition(sorter, projection) == "TooFar"
