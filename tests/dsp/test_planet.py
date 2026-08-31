"""The planet's bands, and the paste predicates that depend on which one you are in."""

from __future__ import annotations

import math

import pytest

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import colliders, planet, rules

SEGMENT = colliders.PLANET_SEGMENT


# --- the table and the quantisation ----------------------------------------


def test_the_segment_table_is_512_entries_of_seventeen_values() -> None:
    assert len(planet.SEGMENT_TABLE) == 512
    assert sorted(set(planet.SEGMENT_TABLE)) == [
        1, 4, 8, 16, 20, 32, 40, 60, 80, 100, 120, 160, 200, 240, 300, 400, 500,
    ]  # fmt: skip


def test_the_quantisation_is_evaluated_in_float32_and_that_changes_the_band() -> None:
    """``Mathf.Cos`` is a float32 cosine, and the difference is a whole band.

    ``latitudeIndex / (segment / 4)`` is exactly 2/3 at these points, so the
    cosine is exactly ``cos(pi/3)`` = 0.5 -- the one place a one-ulp difference
    lands on an integer and ``CeilToInt`` sends the two precisions to different
    entries of the table.  Computed in double, ``segment = 144`` at band index 24
    would be an 80-segment band; the game's float32 makes it 60.

    Terrestrial planets (``segment = 200``) are NOT among these, and that is
    worth stating: the narrowing is unfalsifiable on the only planet size we
    currently emit for, and it is here because
    :func:`~flab2bp.dsp.planet.determine_longitude_segment_count` takes a
    ``segment`` argument and must be right for the values it accepts.
    """
    table = planet.SEGMENT_TABLE

    def in_double(k: int, segment: int) -> int:
        raw = math.ceil(abs(math.cos(k / (segment / 4.0) * math.pi * 0.5)) * segment)
        return table[raw] if raw < 500 else (raw + 49) // 100 * 100

    disagree = [
        (segment, k)
        for segment, k in ((144, 24), (180, 30), (540, 90), (900, 150))
        if in_double(k, segment) != planet.determine_longitude_segment_count(k, segment)
    ]
    assert disagree == [(144, 24), (180, 30), (540, 90), (900, 150)]
    assert planet.determine_longitude_segment_count(24, 144) == 60
    assert in_double(24, 144) == 80


def test_the_two_band_index_spellings_agree() -> None:
    """``GetLongitudeSegmentCount``'s decrement and ``CalcSegmentsAcross``'s -0.1.

    The game writes the grid-row-to-band-index map twice, once as
    ``if (idx > 0) idx--; idx / 5`` (``BlueprintUtils.cs:229-233``) and once as
    ``FloorToInt(Max(0f, Abs(gridIdx / 5f) - 0.1f))`` (``PlanetGrid.cs:1855``).
    They must agree on every integer grid index or this module is porting one of
    them wrongly.
    """
    for g in range(-planet.pole_grid_idx(SEGMENT), planet.pole_grid_idx(SEGMENT) + 1):
        other = math.floor(max(0.0, abs(g / 5.0) - 0.1))
        assert planet.longitude_segment_count(g, SEGMENT) == (
            planet.determine_longitude_segment_count(other, SEGMENT)
        ), g


# --- the band table ---------------------------------------------------------


#: ``(area_segments, latitude_index_lo, latitude_index_hi, grid_lo, grid_hi, rows)``
#: for a terrestrial planet, read off the game's own functions.
TERRESTRIAL = (
    (200, 0, 15, 1, 80, 160),
    (160, 16, 25, 81, 130, 50),
    (120, 26, 30, 131, 155, 25),
    (100, 31, 35, 156, 180, 25),
    (80, 36, 38, 181, 195, 15),
    (60, 39, 41, 196, 210, 15),
    (40, 42, 43, 211, 220, 10),
    (32, 44, 45, 221, 230, 10),
    (20, 46, 46, 231, 235, 5),
    (16, 47, 47, 236, 240, 5),
    (8, 48, 48, 241, 245, 5),
    (4, 49, 50, 246, 250, 5),
)


def test_the_band_table_is_the_game_for_a_terrestrial_planet() -> None:
    got = tuple(
        (b.area_segments, b.latitude_index_lo, b.latitude_index_hi, b.grid_lo, b.grid_hi, b.rows)
        for b in planet.bands(SEGMENT)
    )
    assert got == TERRESTRIAL
    assert [b.columns for b in planet.bands(SEGMENT)] == [
        b[0] * 5 for b in TERRESTRIAL
    ]


def test_the_equatorial_band_has_160_square_capacity() -> None:
    """The equatorial band has 160 lateral squares, as the planet grid publishes.

    The snapped grid indices still run from ``-80..80`` inclusive, which gives a
    full-height blueprint two legal anchor rows.  Capacity counts squares, not
    the 161 boundary indices that surround them.
    """
    band = planet.bands(SEGMENT)[0]
    assert (band.rows, band.columns) == (160, 1000)
    assert band.anchors(160) == (-80, -79)
    assert planet.area_count(-80, 80, SEGMENT) == 1
    assert planet.area_count(-81, 80, SEGMENT) == 2
    assert planet.area_count(-80, 81, SEGMENT) == 2


def test_terrestrial_band_dimensions_are_exact_and_ordered_pole_to_equator() -> None:
    assert tuple(
        (band.rows, band.columns)
        for band in sorted(planet.bands(SEGMENT), key=lambda candidate: candidate.area_segments)
    ) == (
        (5, 20),
        (5, 40),
        (5, 80),
        (5, 100),
        (10, 160),
        (10, 200),
        (15, 300),
        (15, 400),
        (25, 500),
        (25, 600),
        (50, 800),
        (160, 1000),
    )


@pytest.mark.parametrize("band", planet.bands(SEGMENT), ids=lambda b: str(b.area_segments))
def test_every_bands_rows_are_exactly_what_area_count_permits(band: planet.Band) -> None:
    """Every advertised capacity window stays inside one game area.

    Non-equatorial bands are bounded by grid rows.  The equatorial published
    capacity is 160 squares although its two legal full-height placements use
    the 161 snapped indices surrounding those squares.
    """
    for anchor in band.anchors(band.rows):
        assert planet.area_count(anchor, anchor + band.rows - 1, SEGMENT) == 1
    assert band.anchors(band.rows + 1) == ()
    top = band.grid_hi
    if top < planet.pole_grid_idx(SEGMENT) and not band.is_equatorial:
        assert planet.area_count(top - band.rows, top, SEGMENT) == 2


def test_area_count_is_the_cross_tropic_predicate() -> None:
    """One area inside a band, two the moment a window steps over the boundary."""
    assert planet.area_count(81, 130, SEGMENT) == 1  # band 160, exactly
    assert planet.area_count(80, 130, SEGMENT) == 2  # one row into band 200
    assert planet.area_count(81, 131, SEGMENT) == 2  # one row into band 120
    assert planet.area_count(1, 250, SEGMENT) == len(planet.bands(SEGMENT))


# --- picking a band ---------------------------------------------------------


def test_band_for_extent_picks_the_smallest_band_not_the_widest() -> None:
    """Smallest means fewest segments, i.e. most poleward and most compressed.

    Read the second line against the first: one extra ROW takes the extent from
    the 4-segment band, whose 20 columns still hold it, all the way out to 32 --
    because every band between them is only five rows tall.  Height is what
    binds, and it binds in jumps.
    """
    assert planet.band_for_extent(10, 5, SEGMENT).band.area_segments == 4
    assert planet.band_for_extent(10, 6, SEGMENT).band.area_segments == 32
    assert planet.band_for_extent(10, 11, SEGMENT).band.area_segments == 32
    assert planet.band_for_extent(30, 25, SEGMENT).band.area_segments == 100
    assert planet.band_for_extent(30, 31, SEGMENT).band.area_segments == 160
    assert planet.band_for_extent(60, 55, SEGMENT).band.area_segments == 200


def test_band_for_extent_considers_both_orientations() -> None:
    """A quarter turn changes which extent has to fit the band's row count."""
    # 10 wide by 11 tall does NOT fit band 32's ten rows upright; turned, its
    # eleven columns fit the band's 160 and its ten rows fit exactly.
    turned = planet.band_for_extent(10, 11, SEGMENT)
    assert turned.rotated and turned.rows == 10 and turned.columns == 11

    # Wide and short: 6 rows upright already fits, so no turn is needed.
    wide = planet.band_for_extent(120, 6, SEGMENT)
    assert not wide.rotated and wide.rows == 6 and wide.columns == 120
    assert wide.band.area_segments == 32

    square = planet.band_for_extent(7, 7, SEGMENT)
    assert not square.rotated  # ties go to the orientation we emitted

    # Ignoring the turn would refuse this outright: 161 rows upright is the
    # equatorial band, 10 rows turned is band 40.
    tall = planet.band_for_extent(10, 161, SEGMENT)
    assert tall.rotated and tall.band.area_segments == 40


def test_band_for_extent_refuses_when_nothing_fits() -> None:
    """A blueprint beyond the authoritative height or width pastes nowhere."""
    with pytest.raises(planet.BandRefusal, match="fits no band"):
        planet.band_for_extent(161, 161, SEGMENT)
    with pytest.raises(planet.BandRefusal, match="fits no band"):
        planet.band_for_extent(1001, 1001, SEGMENT)
    assert planet.band_for_extent(160, 160, SEGMENT).band.area_segments == 200


def test_the_width_bound_is_the_bands_own_column_count() -> None:
    """Width binds only in the narrow bands, and there it really does."""
    assert planet.band_for_extent(20, 5, SEGMENT).band.area_segments == 4
    assert planet.band_for_extent(21, 5, SEGMENT).band.area_segments == 8


def test_anchors_are_every_window_in_the_band_and_no_others() -> None:
    band = planet.bands(SEGMENT)[1]  # 160, grid 81..130 and its southern mirror
    assert band.anchors(50) == (-130, 81)
    assert band.anchors(49) == (-130, -129, 81, 82)
    assert band.anchors(51) == ()
    equator = planet.bands(SEGMENT)[0]
    assert equator.anchors(161) == ()
    assert equator.anchors(160) == (-80, -79)
    assert tuple(equator.anchor_ranges(160)) == (range(-80, -78),)
    assert tuple(band.anchor_ranges(49)) == (
        range(-130, -128),
        range(81, 83),
    )
    for anchor in band.anchors(50):
        assert planet.area_count(anchor, anchor + 49, SEGMENT) == 1


def test_full_height_polar_fit_has_only_the_two_unpadded_hemisphere_anchors() -> None:
    band = next(band for band in planet.bands(SEGMENT) if band.area_segments == 4)
    fit = planet.Fit(band=band, rotated=False, rows=5, columns=20)

    projections = planet.projections_for(fit)

    assert tuple(projection.anchor_row for projection in projections) == (-250, 246)
    assert all(projection.quadrant == 0 for projection in projections)


# --- the projection ---------------------------------------------------------


def test_the_projection_agrees_with_colliders_at_the_equator() -> None:
    """This module carries its own ``SphericalRotation``; it must be the same one.

    ``colliders.preview_pose`` is the existing, exercised port of the same
    ``RefreshBuildPreview`` arithmetic, and at ``anchor_lat = 0`` its longitude
    step resolves to ``segmentTable[200] = 200`` -- the one band where its band
    index is right.  So the equator is where the two can be compared, and any
    divergence in the quaternion maths or the direction convention shows up
    here.
    """
    projection = planet.Projection(
        band=planet.bands(SEGMENT)[0], anchor_row=0, segment=SEGMENT, radius=colliders.PLANET_RADIUS
    )
    for x, y, z, yaw in ((0, 0, 0, 0.0), (7, -3, 1, 90.0), (-11, 5, 0, 270.0), (2, 2, 3, 45.0)):
        mine = projection.pose(x, y, z, yaw)
        theirs = colliders.preview_pose(x, y, z, yaw, anchor_lat=0.0)
        assert mine[0] == pytest.approx(theirs[0], abs=1e-9)
        assert planet.quaternion_angle_deg(mine[1], theirs[1]) == pytest.approx(0.0, abs=1e-6)


def test_the_projection_uses_the_bands_own_step() -> None:
    """The longitude step is the band's, and the band contains every row it spans."""
    for band in planet.bands(SEGMENT):
        for anchor in band.anchors(1):
            assert planet.longitude_segment_count(anchor, SEGMENT) == band.area_segments
        projection = planet.Projection(
            band=band, anchor_row=band.grid_lo, segment=SEGMENT,
            radius=colliders.PLANET_RADIUS,
        )
        assert projection.longitude_step == pytest.approx(
            planet.longitude_rad_per_grid(band.area_segments)
        )


def test_a_column_is_a_tile_at_the_equator_and_narrower_everywhere_else() -> None:
    """The flat model's ``GRID_ARC`` is the supremum, and this is by how much.

    ``colliders``' docstring states that the flat grid is the supremum of real
    column spacing inside the equatorial band.  If that is true, the equator
    reproduces ``GRID_ARC`` exactly and every other row in every band is at or
    below it.  The worst case over the whole planet is what a layout that must
    survive its smallest band is really up against.
    """
    equator = planet.Projection(
        band=planet.bands(SEGMENT)[0], anchor_row=0, segment=SEGMENT,
        radius=colliders.PLANET_RADIUS,
    )
    # GRID_ARC assumes a shell of exactly ``radius``; a build sits 0.2 above it.
    lift = (colliders.PLANET_RADIUS + 0.2) / colliders.PLANET_RADIUS
    assert equator.column_arc() == pytest.approx(colliders.GRID_ARC * lift, rel=1e-12)
    assert equator.row_arc() == pytest.approx(colliders.GRID_ARC * lift, rel=1e-12)

    pole = planet.pole_grid_idx(SEGMENT)
    arcs = {
        (band.area_segments, row): planet.Projection(
            band=band, anchor_row=row, segment=SEGMENT, radius=colliders.PLANET_RADIUS
        ).column_arc()
        for band in planet.bands(SEGMENT)
        for row in range(band.grid_lo, band.grid_hi + 1)
    }
    # A column has no width AT the pole -- every longitude meets there.  That is
    # the game's geometry, not a degenerate case of ours, and ``CalcSegmentsAcross``
    # carries its own 0.0048 floor for exactly this row.
    assert arcs[(4, pole)] == pytest.approx(0.0, abs=1e-12)

    ratios = {k: v / (colliders.GRID_ARC * lift) for k, v in arcs.items()}
    off_pole = min(v for (_seg, row), v in ratios.items() if row != pole)
    assert off_pole == pytest.approx(0.3142, abs=5e-4)  # band 4, one row off the pole

    # A COLUMN CAN ALSO BE WIDER THAN A TILE, which the "flat is the supremum"
    # reading of the flat model does not survive outside the equatorial band:
    # the quantisation overshoots at a band's equatorward edge.
    assert max(ratios.values()) == pytest.approx(1.4130, abs=5e-4)  # band 8, row 241

    # Inside the equatorial band -- where everything we emit today lands --
    # the flat model IS the supremum, and the worst case is 0.876 of a tile.
    band200 = min(v for (seg, _row), v in ratios.items() if seg == 200)
    # Row 1, not row 0: ``grid_lo`` is 1, and cos of one row is 0.99998.
    assert max(v for (seg, _row), v in ratios.items() if seg == 200) == pytest.approx(
        1.0, abs=1e-4
    )
    assert band200 == pytest.approx(0.8763, abs=5e-4)


# --- CalcSegmentsAcross and the sorter ladder -------------------------------


def _sorter(**kw: float | bool) -> planet.Sorter:
    base: dict[str, float | bool] = dict(
        x=0.0, y=0.0, z=0.0, x2=0.0, y2=0.0, z2=0.0, yaw=0.0, yaw2=0.0,
        input_belt=False, output_belt=False, ref_x=0.0, ref_y=0.0, ref_z=0.0,
    )
    base.update(kw)
    return planet.Sorter(**base)  # type: ignore[arg-type]


def test_calc_segments_across_counts_grid_cells_at_the_equator() -> None:
    projection = planet.Projection(
        band=planet.bands(SEGMENT)[0], anchor_row=0, segment=SEGMENT,
        radius=colliders.PLANET_RADIUS,
    )
    for span in (1, 2, 3, 4):
        a = projection.position(0, 0, 0)
        b = projection.position(span, 0, 0)
        got = planet.calc_segments_across(a, a, b, SEGMENT)
        assert got == pytest.approx(span, rel=2e-4), span


def test_calc_segments_across_is_a_grid_measure_and_survives_compression() -> None:
    """A three-column sorter is three cells across in EVERY band.

    This is the property that makes the game's ``num133`` a grid rule rather than
    a distance rule, and it is why it cannot be replaced by the world-unit length
    bound: the world length of that same sorter shrinks by 22% between the
    equator and the narrowest column on the planet, and ``num128`` does not move.
    """
    lengths = []
    for band in planet.bands(SEGMENT):
        row = min(band.grid_hi, planet.pole_grid_idx(SEGMENT) - 1)
        projection = planet.Projection(
            band=band, anchor_row=row, segment=SEGMENT, radius=colliders.PLANET_RADIUS
        )
        a = projection.position(0, 0, 0)
        b = projection.position(3, 0, 0)
        across = planet.calc_segments_across(a, a, b, SEGMENT)
        if band.area_segments == 4:
            # The one place the game's own ``Mathf.Max(0.0048f, ...)`` floor
            # binds: a column here is 0.002 of a radian, below the floor, so
            # ``CalcSegmentsAcross`` divides by a pitch WIDER than the real one
            # and reports 1.19 cells for three columns.  That is the game's
            # arithmetic, and a port that "fixed" it would be inventing a rule.
            assert across == pytest.approx(1.1885, abs=1e-3)
        else:
            # Never above three, never far below.  The shortfall is the game's
            # own: it divides a CHORD by an ARC, so it under-reports by
            # ``(delta lambda)^2 / 24`` -- 1e-6 in band 200 and 0.9% in band 8.
            assert 2.97 <= across <= 3.0, band.area_segments
        lengths.append(math.dist(a, b))
    assert min(lengths) / max(lengths) < 0.8


def test_a_four_cell_sorter_passes_the_ported_length_test_and_the_game_refuses_it() -> None:
    """The gap ``rules.SORTER_LENGTH`` alone leaves open.

    A four-cell machine-to-machine sorter at the equator is 5.03 world units
    long, comfortably inside ``SORTER_LENGTH[0]``'s 7.5, and ``num128`` is 4.0
    against ``SORTER_SEGMENTS_MAX[0]``'s 3.799.  The game reports ``TooFar``;
    the world-unit test cannot.
    """
    projection = planet.Projection(
        band=planet.bands(SEGMENT)[0], anchor_row=0, segment=SEGMENT,
        radius=colliders.PLANET_RADIUS,
    )
    sorter = _sorter(x=0.0, y=0.0, x2=0.0, y2=4.0, ref_y=2.0)
    world = math.dist(
        projection.position(sorter.x, sorter.y, sorter.z),
        projection.position(sorter.x2, sorter.y2, sorter.z2),
    )
    assert rules.SORTER_LENGTH[0][0] < world < rules.SORTER_LENGTH[0][1]
    assert planet.sorter_condition(sorter, projection) == "TooFar"

    three = _sorter(x=0.0, y=0.0, x2=0.0, y2=3.0, ref_y=1.5)
    assert planet.sorter_condition(three, projection) is None


def test_the_sorter_ladder_reports_each_condition_by_name() -> None:
    projection = planet.Projection(
        band=planet.bands(SEGMENT)[0], anchor_row=0, segment=SEGMENT,
        radius=colliders.PLANET_RADIUS,
    )
    # TooClose on world length: two coincident ends.
    assert planet.sorter_condition(_sorter(), projection) == "TooClose"
    # TooSkew: a sorter running north with both ends facing east.
    skew = _sorter(y2=2.0, yaw=90.0, yaw2=90.0, ref_y=1.0)
    assert planet.sorter_condition(skew, projection) == "TooSkew"
    # TooSkew on the pair test alone: ends 180 degrees apart about the axis.
    pair = _sorter(y2=2.0, yaw=0.0, yaw2=180.0, ref_y=1.0)
    assert planet.sorter_condition(pair, projection) == "TooSkew"


def test_a_sorter_legal_at_the_equator_can_be_refused_poleward_in_its_own_band() -> None:
    """The whole point: legality is a function of the band, not of the layout.

    A belt-to-belt sorter one column long is 1.257 world units at the equator and
    1.101 at the poleward edge of the SAME band -- still legal.  Push it into the
    narrowest band on the planet and the same sorter is 0.98.  What actually
    bites first is the combined ``num134`` floor, which the equator clears and a
    compressed band does not, and neither test exists in the flat model.
    """
    band = planet.bands(SEGMENT)[0]

    def at(row: int) -> planet.Projection:
        return planet.Projection(
            band=band, anchor_row=row, segment=SEGMENT, radius=colliders.PLANET_RADIUS
        )

    lengths = [
        math.dist(at(row).position(0, 0, 0), at(row).position(1, 0, 0))
        for row in (0, 80)
    ]
    lift = (colliders.PLANET_RADIUS + 0.2) / colliders.PLANET_RADIUS
    # ``rel`` covers chord-against-arc over one tile, which is (step^2)/24 = 1.6e-6.
    assert lengths[0] == pytest.approx(colliders.GRID_ARC * lift, rel=5e-6)
    assert lengths[1] < lengths[0]
    assert lengths[1] / lengths[0] == pytest.approx(0.876, abs=5e-4)


# --- collisions at a band ---------------------------------------------------


def test_every_shipped_collider_quaternion_is_identity() -> None:
    """The guard behind :func:`planet.collisions_at` using one box builder.

    ``colliders``' docstring says the query side and the target side agree
    "because every build collider in the shipped data has ``q`` identity".  That
    is a fact about the data, so it is checked against the data.
    """
    from flab2bp.dsp.colliders import _table

    for model, entries in _table().items():
        for _pos, _ext, q in entries:
            assert q == (0.0, 0.0, 0.0, 1.0), model


def test_collisions_at_the_equator_reproduce_the_flat_model() -> None:
    """At the equator the projection IS the flat grid, so the verdicts must match.

    Assembling Machine Mk.I is 3.82 world units wide against a 1.2566 tile, so
    three tiles apart collides and four does not -- the example
    ``colliders``' own docstring gives.
    """
    machine = cat.building(2303).model_index  # Assembling Machine Mk.I
    projection = planet.Projection(
        band=planet.bands(SEGMENT)[0], anchor_row=0, segment=SEGMENT,
        radius=colliders.PLANET_RADIUS,
    )
    for pitch, expected in ((3, [(0, 1)]), (4, [])):
        pair = [
            colliders.Placed(machine, 0.0, 0.0, 0.0, 0.0),
            colliders.Placed(machine, float(pitch), 0.0, 0.0, 0.0),
        ]
        assert colliders.collisions(pair) == expected, pitch
        assert planet.collisions_at(pair, projection) == expected, pitch


def test_a_pair_that_is_clear_flat_collides_at_the_poleward_edge_of_its_band() -> None:
    """The gap the flat model leaves, made concrete.

    Two Matrix Labs five columns apart are clear at the equator and collide
    north of it -- ``colliders``' docstring says so and does not check it,
    because the flat model cannot.  The band model can: the same pair, in the
    smallest band that holds it, is a genuine ``Collide``.
    """
    lab = cat.building(2901).model_index  # Matrix Lab, 2.8 half-extent
    pair = [
        colliders.Placed(lab, 0.0, 0.0, 0.0, 0.0),
        colliders.Placed(lab, 5.0, 0.0, 0.0, 0.0),
    ]
    band = planet.bands(SEGMENT)[0]
    equator = planet.Projection(
        band=band, anchor_row=0, segment=SEGMENT, radius=colliders.PLANET_RADIUS
    )
    poleward = planet.Projection(
        band=band, anchor_row=band.grid_hi, segment=SEGMENT, radius=colliders.PLANET_RADIUS
    )
    assert colliders.collisions(pair) == []
    assert planet.collisions_at(pair, equator) == []
    assert planet.collisions_at(pair, poleward) == [(0, 1)]

    # And it is not that the band model convicts everything: six columns is
    # clear at the same anchor, and five columns is clear one band inward.
    six = [
        colliders.Placed(lab, 0.0, 0.0, 0.0, 0.0),
        colliders.Placed(lab, 6.0, 0.0, 0.0, 0.0),
    ]
    assert planet.collisions_at(six, poleward) == []




def test_collider_radius_is_the_exact_farthest_collider_corner() -> None:
    model = cat.building(2303).model_index
    expected = max(
        math.sqrt(
            sum(
                (abs(coordinate) + half_extent) ** 2
                for coordinate, half_extent in zip(position, extent, strict=True)
            )
        )
        for position, extent, _rotation in colliders.build_colliders(model)
    )

    assert planet.collider_radius(model) == pytest.approx(expected)


def test_candidate_focused_broad_phase_matches_all_pairs_without_peer_pair_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = cat.building(2303).model_index
    buildings = tuple(
        colliders.Placed(model, 0.0, 0.0, 0.0, 0.0)
        for _ in range(32)
    )
    band = planet.bands(SEGMENT)[0]
    _ = planet.collider_radius(model)
    square_roots = 0
    sqrt = planet.math.sqrt

    def counted_sqrt(value: float) -> float:
        nonlocal square_roots
        square_roots += 1
        return sqrt(value)

    monkeypatch.setattr(planet.math, "sqrt", counted_sqrt)
    all_pairs = planet.candidate_pairs(
        buildings,
        band,
        SEGMENT,
        colliders.PLANET_RADIUS,
    )
    all_pair_roots = square_roots
    square_roots = 0
    candidate_position = 11
    focused = planet.candidate_pairs(
        buildings,
        band,
        SEGMENT,
        colliders.PLANET_RADIUS,
        candidate_position=candidate_position,
    )

    assert focused == [
        pair for pair in all_pairs
        if candidate_position in pair
    ]
    assert all_pair_roots == len(buildings) * (len(buildings) - 1) // 2
    assert square_roots == len(buildings) - 1


@pytest.mark.parametrize(("dx", "dy"), ((3.04, 0.0), (0.0, 3.04)))
@pytest.mark.parametrize("quadrant", (0, 1))
def test_candidate_focused_pairs_preserve_near_edge_exact_verdict(
    dx: float,
    dy: float,
    quadrant: int,
) -> None:
    model = cat.building(2303).model_index
    buildings = (
        colliders.Placed(model, 0.0, 0.0, 0.0, 0.0),
        colliders.Placed(model, dx, dy, 0.0, 0.0),
        colliders.Placed(model, 20.0, 20.0, 0.0, 0.0),
    )
    band = planet.bands(SEGMENT)[0]
    projection = planet.Projection(
        band,
        0,
        SEGMENT,
        colliders.PLANET_RADIUS,
        quadrant=quadrant,
    )
    all_pairs = planet.candidate_pairs(
        buildings,
        band,
        SEGMENT,
        colliders.PLANET_RADIUS,
    )
    candidate_position = 1
    focused = planet.candidate_pairs(
        buildings,
        band,
        SEGMENT,
        colliders.PLANET_RADIUS,
        candidate_position=candidate_position,
    )

    assert focused == [
        pair for pair in all_pairs
        if candidate_position in pair
    ]
    assert planet.collisions_at(buildings, projection, focused) == [
        pair
        for pair in planet.collisions_at(buildings, projection, all_pairs)
        if candidate_position in pair
    ]


def test_candidate_pairs_cancels_inside_focused_peer_scan() -> None:
    model = cat.building(2303).model_index
    buildings = tuple(
        colliders.Placed(model, float(index), 0.0, 0.0, 0.0)
        for index in range(32)
    )
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 6

    with pytest.raises(planet.ProjectionCancelled):
        planet.candidate_pairs(
            buildings,
            planet.bands(SEGMENT)[0],
            SEGMENT,
            colliders.PLANET_RADIUS,
            candidate_position=11,
            cancelled=cancelled,
        )

    assert checks == 6


def test_collisions_at_cancels_inside_obb_products_without_box_cache_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = cat.building(2303).model_index
    buildings = tuple(
        colliders.Placed(model, 0.0, 0.0, 0.0, 0.0)
        for _ in range(3)
    )
    projection = planet.Projection(
        planet.bands(SEGMENT)[0],
        0,
        SEGMENT,
        colliders.PLANET_RADIUS,
    )
    overlaps = 0
    box_cache: dict[
        tuple[colliders.Placed, planet.Projection],
        tuple[colliders.Box, ...],
    ] = {}

    def overlap_once(_left: colliders.Box, _right: colliders.Box) -> bool:
        nonlocal overlaps
        overlaps += 1
        return False

    monkeypatch.setattr(colliders, "obb_overlap", overlap_once)

    with pytest.raises(planet.ProjectionCancelled):
        planet.collisions_at(
            buildings,
            projection,
            ((0, 1), (0, 2)),
            _box_cache=box_cache,
            cancelled=lambda: overlaps >= 1,
        )

    assert overlaps == 1
    assert box_cache == {}
