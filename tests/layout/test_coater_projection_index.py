"""Reusable coater broadphase must preserve the authoritative first refusal."""

from dataclasses import replace

from flab2bp.dsp import catalog, colliders, planet
from flab2bp.layout import finalize


def test_cached_coater_queries_preserve_projection_seams_models_and_input_order() -> None:
    coater_model = catalog.building(catalog.SPRAY_COATER_ID).model_index
    cache = finalize._ProjectionCache(finalize._ProjectionCounters())
    # Deliberately non-index order: the first refusal follows input positions,
    # not placement IDs or KD traversal order. Duplicate positions stay distinct.
    coaters = (
        (90, colliders.Placed(coater_model, 0, 0, 0, 90.0)),
        (10, colliders.Placed(coater_model, 0, 0, 0, 0.0)),
        (50, colliders.Placed(coater_model, 6, 3, 1, 180.0)),
    )
    bands = planet.bands()
    selected_bands = (
        next(band for band in bands if band.area_segments == 160),
        min(bands, key=lambda band: band.area_segments),
    )
    for band in selected_bands:
        for quadrant in (0, 1):
            for anchor in (band.grid_lo, band.grid_hi):
                projection = planet.Projection(
                    band=band,
                    anchor_row=anchor,
                    segment=colliders.PLANET_SEGMENT,
                    radius=colliders.PLANET_RADIUS,
                    quadrant=quadrant,
                )
                for model in (38, 39, 40):
                    seam = band.columns if quadrant == 0 else 0
                    seam_y = band.columns if quadrant == 1 else 0
                    touching = (70, colliders.Placed(model, seam, seam_y, 0, 0.0))
                    remote = (20, colliders.Placed(model, 25, 25, 6, 90.0))
                    for splitters in ((remote,), (touching,), (remote, touching)):
                        want = next(
                            (
                                failure
                                for coater in coaters
                                for splitter in splitters
                                if (
                                    failure := finalize.projected_coater_splitter_failure(
                                        coater, splitter, projection
                                    )
                                )
                                is not None
                            ),
                            None,
                        )
                        assert cache.addon_splitter_failure(coaters, splitters, projection) == want
                        assert cache.addon_splitter_failure(coaters, splitters, projection) == want


def test_cached_coater_queries_replace_geometry_and_retain_first_failure_order() -> None:
    coater_model = catalog.building(catalog.SPRAY_COATER_ID).model_index
    band = next(band for band in planet.bands() if band.area_segments == 160)
    projection = planet.Projection(
        band=band,
        anchor_row=-130,
        segment=colliders.PLANET_SEGMENT,
        radius=colliders.PLANET_RADIUS,
    )
    placed = colliders.Placed(coater_model, 26, 15, 0, 90.0)
    first = (90, placed)
    second = (10, placed)
    splitters = ((70, colliders.Placed(38, 25, 17, 1, 0.0)),)
    cache = finalize._ProjectionCache(finalize._ProjectionCounters())
    original = (first, second)
    reversed_order = (second, first)
    translated = tuple((index, replace(coater, x=100)) for index, coater in original)
    for coaters, expected_pair in (
        (original, (90, 70)),
        (reversed_order, (10, 70)),
        (translated, None),
        (original, (90, 70)),
    ):
        failure = cache.addon_splitter_failure(coaters, splitters, projection)
        assert (None if failure is None else failure.buildings) == expected_pair
