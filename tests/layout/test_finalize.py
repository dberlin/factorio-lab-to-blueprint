"""Strategy-independent exact cleanup of emitted placements."""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from typing import cast

import pytest

from flab2bp.dsp import catalog, codec, colliders, planet, rules
from flab2bp.layout import finalize
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import AreaFrame, PlacedBuilding, Placement
from tests.layout.test_freeform import two_stage_spec


def _belt(x: int, y: int, *, output: int | None) -> PlacedBuilding:
    item_id = min(catalog.BELT_IDS)
    return PlacedBuilding(
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=x,
        y=y,
        z=Fraction(),
        output_obj=output,
    )


def _building(
    item_id: int,
    x: int,
    y: int,
    *,
    z: Fraction = Fraction(),
    yaw: float = 0.0,
) -> PlacedBuilding:
    info = catalog.building(item_id)
    return PlacedBuilding(
        item_id=item_id,
        model_index=info.model_index,
        x=x,
        y=y,
        z=z,
        width=info.width,
        height=info.height,
        yaw=yaw,
    )


def _extent(width: int, height: int) -> tuple[PlacedBuilding, PlacedBuilding]:
    return (
        _belt(0, 0, output=None),
        _belt(width - 1, height - 1, output=None),
    )


@dataclass(frozen=True)
class _Report:
    errors: tuple[object, ...] = ()


def test_remove_buildings_bypasses_removed_chain_and_reindexes() -> None:
    placement = Placement(
        buildings=(
            _belt(0, 0, output=1),
            _belt(1, 0, output=2),
            _belt(2, 0, output=None),
        )
    )

    changed = finalize._remove_buildings(placement, frozenset({1}))

    assert [(belt.x, belt.output_obj) for belt in changed.buildings] == [
        (0, 1),
        (2, None),
    ]


def test_compaction_prunes_open_belt_leaves_to_a_structural_fixed_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placement = Placement(
        buildings=(
            _belt(0, 1, output=1),
            _belt(1, 1, output=2),
            _belt(2, 1, output=None),
            _belt(1, 0, output=1),
        )
    )
    calls: list[Placement] = []

    def certify(candidate: Placement, *_args: object, **_kwargs: object) -> _Report:
        calls.append(candidate)
        return _Report()

    monkeypatch.setattr(finalize, "_certify", certify)
    compacted = finalize.compact_open_boundary_belts(
        placement,
        two_stage_spec(),
        expect_power=False,
    )

    assert len(calls) == 1
    assert compacted.area == 1
    assert [(belt.x, belt.y) for belt in compacted.buildings] == [(1, 1)]


def test_framed_boundary_fallback_returns_unfinalized_smaller_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smelter = _building(2302, 1, 0)
    placement = Placement(
        buildings=(
            _belt(0, 1, output=1),
            smelter,
        ),
        stats={"area": 12.0},
        frame=AreaFrame(4, 3, 4, (4,), False),
    )
    calls: list[Placement] = []

    def certify(candidate: Placement, *_args: object, **_kwargs: object) -> _Report:
        calls.append(candidate)
        return _Report(errors=(object(),)) if len(calls) == 1 else _Report()

    monkeypatch.setattr(finalize, "_certify", certify)

    compacted = finalize.compact_open_boundary_belts(
        placement,
        two_stage_spec(),
        expect_power=False,
    )

    assert len(calls) == 2
    assert compacted.buildings == (smelter,)
    assert compacted.frame is None
    assert compacted.bounds == (1, 0, 3, 2)
    assert compacted.area == 9
    assert compacted.stats["area"] == 9.0
    assert finalize.finalize_placement(compacted, BandPolicy("portable")).frame is not None


def test_compaction_preserves_original_when_certification_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placement = Placement(
        buildings=(
            _belt(0, 0, output=1),
            _belt(1, 0, output=None),
        )
    )

    def reject(*_args: object, **_kwargs: object) -> _Report:
        return _Report(errors=(object(),))

    monkeypatch.setattr(finalize, "_certify", reject)

    assert (
        finalize.compact_open_boundary_belts(
            placement,
            two_stage_spec(),
            expect_power=False,
        )
        is placement
    )


@pytest.mark.parametrize(("width", "height"), ((43, 35), (35, 43)))
def test_finalization_selects_the_smallest_band_for_broke2_extent(
    width: int,
    height: int,
) -> None:
    placement = Placement(buildings=_extent(width, height))

    finalized = finalize.finalize_placement(placement, BandPolicy("portable"))

    assert finalized.frame == AreaFrame(width, height, 160, (160, 200), False)


def test_finalization_physically_rotates_an_extent_that_only_fits_turned() -> None:
    placement = Placement(buildings=_extent(10, 161))

    finalized = finalize.finalize_placement(placement, BandPolicy("portable"))
    area = codec.placement_to_blueprint(finalized).areas[0]

    assert finalized.bounds == (0, 0, 160, 9)
    assert finalized.frame == AreaFrame(161, 10, 40, (40, 60, 80), True)
    assert (area.width, area.height, area.area_segments) == (161, 10, 40)


def test_broke2_tower_pair_uses_the_safe_smallest_band_orientation() -> None:
    placement = Placement(
        buildings=(
            *_extent(43, 35),
            _building(catalog.TESLA_TOWER_ID, 22, 10),
            _building(catalog.TESLA_TOWER_ID, 20, 8),
        )
    )

    finalized = finalize.finalize_placement(placement, BandPolicy("160"))

    assert finalized.frame == AreaFrame(35, 43, 160, (160,), True)
    assert finalized.bounds == (0, 0, 34, 42)



def _required_power_projections(primary_band: int) -> tuple[planet.Projection, ...]:
    by_segments = {band.area_segments: band for band in planet.bands()}
    primary = by_segments[primary_band]
    return tuple(
        planet.Projection(
            band=band,
            anchor_row=anchor,
            segment=colliders.PLANET_SEGMENT,
            radius=colliders.PLANET_RADIUS,
        )
        for band in finalize.target_bands(primary, BandPolicy("portable"))
        for anchor in band.anchors(5)
    )


def _diagonal_tesla_pair(dx: int = 2, dy: int = 2) -> tuple[
    tuple[int, PlacedBuilding, rules.PowerNode],
    ...,
]:
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    return (
        (0, _building(catalog.TESLA_TOWER_ID, 0, 0), tower.power_node),
        (1, _building(catalog.TESLA_TOWER_ID, dx, dy), tower.power_node),
    )


def test_projected_power_failure_rejects_flat_legal_pair_in_required_projection() -> None:
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    assert rules.power_node_condition(
        tower.power_node,
        tower.power_node,
        8 * colliders.GRID_ARC**2,
    ) is None

    failures = tuple(
        failure
        for projection in _required_power_projections(40)
        if (
            failure := finalize.projected_power_failure(
                _diagonal_tesla_pair(),
                projection,
            )
        )
        is not None
    )

    assert failures
    assert {failure.check for failure in failures} == {"game.power_too_close"}
    assert {failure.band for failure in failures} <= {40, 60, 80}
    assert all("below the 3.5-unit PowerTooClose gate" in failure.detail for failure in failures)
    assert all(
        finalize.projected_power_failure(_diagonal_tesla_pair(3, 2), projection) is None
        for projection in _required_power_projections(40)
    )


def _broke2_coater() -> tuple[int, colliders.Placed]:
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    return (
        4,
        finalize._collision_placed(
            PlacedBuilding(
                item_id=catalog.SPRAY_COATER_ID,
                model_index=coater.model_index,
                x=26,
                y=15,
                yaw=90.0,
            )
        ),
    )


def _broke2_splitter(y: int = 17) -> tuple[int, colliders.Placed]:
    return (
        5,
        finalize._collision_placed(
            _building(catalog.SPLITTER_ID, 25, y, z=Fraction(1))
        ),
    )


def _broke2_projection() -> planet.Projection:
    band = next(band for band in planet.bands() if band.area_segments == 160)
    return planet.Projection(
        band=band,
        anchor_row=-130,
        segment=colliders.PLANET_SEGMENT,
        radius=colliders.PLANET_RADIUS,
    )


def test_projected_coater_splitter_failure_uses_exact_broke2_geometry() -> None:
    failure = finalize.projected_coater_splitter_failure(
        coater=_broke2_coater(),
        splitter=_broke2_splitter(),
        projection=_broke2_projection(),
    )

    assert failure == finalize.ProjectionFailure(
        check="game.addon_splitter_clearance",
        buildings=(4, 5),
        detail=(
            "Splitter connection body enters the Spray Coater projected lateral "
            "keepout"
        ),
        band=160,
    )
    assert (
        finalize.projected_coater_splitter_failure(
            coater=_broke2_coater(),
            splitter=_broke2_splitter(y=18),
            projection=_broke2_projection(),
        )
        is None
    )


def test_broke2_splitter_region_is_rejected_by_projected_addon_keepout() -> None:
    # Original blueprint records: host belt #100, supply belt #478,
    # Spray Coater #479, and Splitter #794.
    placement = Placement(
        buildings=(
            *_extent(43, 35),
            _building(min(catalog.BELT_IDS), 26, 15),
            _building(min(catalog.BELT_IDS), 25, 15, z=Fraction(1)),
            PlacedBuilding(
                item_id=catalog.SPRAY_COATER_ID,
                model_index=catalog.building(catalog.SPRAY_COATER_ID).model_index,
                x=26,
                y=15,
                yaw=90.0,
            ),
            _building(catalog.SPLITTER_ID, 25, 17, z=Fraction(1)),
        )
    )

    with pytest.raises(finalize.ProjectionRefusal) as exc:
        finalize.finalize_placement(placement, BandPolicy("portable"))

    assert exc.value.checks == ("game.addon_splitter_clearance",)
    assert "(4, 5)" in str(exc.value)


def test_portable_refuses_when_required_primary_band_compresses_sorter() -> None:
    belt_id = min(catalog.BELT_IDS)
    sorter_id = catalog.item_id("sorter-1")
    placement = Placement(
        buildings=(
            _building(belt_id, 0, 0),
            _building(belt_id, 1, 0),
            _building(belt_id, 19, 4),
            PlacedBuilding(
                item_id=sorter_id,
                model_index=catalog.building(sorter_id).model_index,
                x=0,
                y=0,
                x2=1,
                y2=0,
                z2=Fraction(),
                yaw=90.0,
                yaw2=90.0,
                input_obj=0,
                output_obj=1,
            ),
        )
    )

    with pytest.raises(finalize.ProjectionRefusal) as exc:
        finalize.finalize_placement(placement, BandPolicy("portable"))

    assert exc.value.checks == ("game.inserter_paste",)


def test_portable_targets_stop_at_the_equator() -> None:
    by_segments = {band.area_segments: band for band in planet.bands()}

    assert tuple(
        band.area_segments
        for band in finalize.target_bands(by_segments[160], BandPolicy("portable"))
    ) == (160, 200)
    assert tuple(
        band.area_segments
        for band in finalize.target_bands(by_segments[200], BandPolicy("portable"))
    ) == (200,)


def test_frame_candidates_cover_both_orientations_and_every_padding_split() -> None:
    placement = Placement(buildings=_extent(2, 2))

    candidates = finalize.frame_candidates(placement, BandPolicy("40"))

    assert {
        (candidate.frame.rotated, candidate.added_rows, candidate.south_padding)
        for candidate in candidates
    } == {
        (rotated, added_rows, south_padding)
        for rotated in (False, True)
        for added_rows in range(5)
        for south_padding in range(added_rows + 1)
    }
    assert all(candidate.frame.width == 2 for candidate in candidates)
    keys = [
        (
            candidate.frame.width * candidate.frame.height,
            candidate.added_rows,
            candidate.frame.rotated,
            candidate.south_padding,
        )
        for candidate in candidates
    ]
    assert keys == sorted(keys)


def test_portable_primary_is_global_and_padding_never_promotes_it() -> None:
    candidates = finalize.frame_candidates(
        Placement(buildings=_extent(21, 5)),
        BandPolicy("portable"),
    )

    assert candidates
    assert {candidate.frame.primary_band for candidate in candidates} == {8}
    assert {candidate.frame.certified_bands for candidate in candidates} == {(8, 16, 20)}


def test_explicit_policy_certifies_only_requested_band() -> None:
    finalized = finalize.finalize_placement(
        Placement(buildings=_extent(3, 3)),
        BandPolicy("40"),
    )

    assert finalized.frame == AreaFrame(3, 3, 40, (40,), False)


def test_explicit_policy_refuses_instead_of_promoting_requested_band() -> None:
    with pytest.raises(finalize.ProjectionRefusal) as caught:
        finalize.finalize_placement(
            Placement(buildings=_extent(21, 5)),
            BandPolicy("4"),
        )

    assert caught.value.failures == (
        finalize.ProjectionFailure(
            check="game.blueprint_area",
            buildings=(),
            detail="frame 21x5 exceeds the requested band's 20x5 capacity",
            band=4,
        ),
    )


def test_certification_can_select_the_other_physical_orientation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placement = Placement(
        buildings=(
            _building(2302, 0, 0),
            _building(2302, 5, 0),
        )
    )

    def fail_wide_orientation(
        tested: tuple[tuple[int, colliders.Placed], ...],
        pairs: tuple[tuple[int, int], ...],
        projection: planet.Projection,
        *,
        counters: finalize._ProjectionCounters | None = None,
    ) -> finalize.ProjectionFailure | None:
        if counters is not None:
            counters.collider_pairs += len(pairs)
        if any(building.x > 1.0 for _index, building in tested):
            return finalize.ProjectionFailure(
                "geom.collide",
                (0, 1),
                "synthetic orientation refusal",
                projection.band.area_segments,
            )
        return None

    monkeypatch.setattr(finalize, "_projected_static_failure", fail_wide_orientation)

    finalized = finalize.finalize_placement(placement, BandPolicy("40"))

    assert finalized.frame == AreaFrame(3, 8, 40, (40,), True)
    assert finalized.bounds == (0, 0, 2, 7)

def test_padding_search_uses_the_first_legal_south_north_split(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placement = Placement(buildings=(_building(2302, 0, 0),))

    def require_south_padding(
        tested: tuple[tuple[int, colliders.Placed], ...],
        pairs: tuple[tuple[int, int], ...],
        projection: planet.Projection,
        *,
        counters: finalize._ProjectionCounters | None = None,
    ) -> finalize.ProjectionFailure | None:
        if counters is not None:
            counters.collider_pairs += len(pairs)
        if tested[0][1].y < 2.0:
            return finalize.ProjectionFailure(
                "geom.collide",
                (0,),
                "synthetic south-edge refusal",
                projection.band.area_segments,
            )
        return None

    monkeypatch.setattr(finalize, "_projected_static_failure", require_south_padding)

    finalized = finalize.finalize_placement(placement, BandPolicy("40"))

    assert finalized.frame == AreaFrame(3, 4, 40, (40,), False)
    assert finalized.buildings[0].y == 1


def test_portable_certifies_same_coordinates_at_every_required_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placement = Placement(
        buildings=(
            _building(2302, 0, 0),
            _building(2302, 0, 0),
        )
    )
    pair_bands: list[int] = []
    seen: list[tuple[int, int, tuple[colliders.Placed, ...]]] = []
    original_pairs = planet.candidate_pairs

    def observed_pairs(
        buildings: tuple[colliders.Placed, ...],
        band: planet.Band,
        segment: int,
        radius: float,
    ) -> list[tuple[int, int]]:
        pair_bands.append(band.area_segments)
        return original_pairs(buildings, band, segment, radius)

    def accept_static(
        tested: tuple[tuple[int, colliders.Placed], ...],
        pairs: tuple[tuple[int, int], ...],
        projection: planet.Projection,
        *,
        counters: finalize._ProjectionCounters | None = None,
    ) -> None:
        if counters is not None:
            counters.collider_pairs += len(pairs)
        seen.append(
            (
                projection.band.area_segments,
                projection.anchor_row,
                tuple(building for _index, building in tested),
            )
        )
        return None

    monkeypatch.setattr(planet, "candidate_pairs", observed_pairs)
    monkeypatch.setattr(finalize, "_projected_static_failure", accept_static)

    finalized = finalize.finalize_placement(placement, BandPolicy("portable"))

    by_segments = {band.area_segments: band for band in planet.bands()}
    expected = [
        (segments, anchor)
        for segments in (4, 8, 16)
        for anchor in by_segments[segments].anchors(3)
    ]
    assert [(segments, anchor) for segments, anchor, _buildings in seen] == expected
    assert len({buildings for _segments, _anchor, buildings in seen}) == 1
    assert pair_bands == [4, 8, 16]
    assert finalized.frame == AreaFrame(3, 3, 4, (4, 8, 16), False)
    assert finalized.stats["projection_frame_candidates"] == 1
    assert finalized.stats["projection_count"] == len(expected)
    assert finalized.stats["projection_collider_pairs"] == len(expected)
    assert finalized.stats["projection_power_pairs"] == 0
    assert finalized.stats["projection_sorters"] == 0


def test_portable_never_promotes_primary_after_projection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_bands: list[int] = []

    def reject(
        _tested: tuple[tuple[int, colliders.Placed], ...],
        pairs: tuple[tuple[int, int], ...],
        projection: planet.Projection,
        *,
        counters: finalize._ProjectionCounters | None = None,
    ) -> finalize.ProjectionFailure | None:
        if counters is not None:
            counters.collider_pairs += len(pairs)
        seen_bands.append(projection.band.area_segments)
        if projection.band.area_segments != 4:
            return None
        return finalize.ProjectionFailure(
            "geom.collide",
            (0, 1),
            "synthetic primary-band refusal",
            projection.band.area_segments,
        )

    monkeypatch.setattr(finalize, "_projected_static_failure", reject)

    with pytest.raises(finalize.ProjectionRefusal) as caught:
        finalize.finalize_placement(
            Placement(buildings=_extent(3, 3)),
            BandPolicy("portable"),
        )

    assert set(seen_bands) == {4, 8, 16}
    assert {failure.band for failure in caught.value.failures} == {4}


def test_five_row_polar_band_passes_only_unpadded_or_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placement = Placement(buildings=_extent(20, 5))
    policy = BandPolicy("portable")

    candidates = finalize.frame_candidates(placement, policy)
    assert [
        (
            candidate.frame.width,
            candidate.frame.height,
            candidate.added_rows,
            candidate.south_padding,
        )
        for candidate in candidates
    ] == [(20, 5, 0, 0)]
    assert finalize.finalize_placement(placement, policy).frame == AreaFrame(
        20,
        5,
        4,
        (4, 8, 16),
        False,
    )

    def reject(
        _tested: tuple[tuple[int, colliders.Placed], ...],
        pairs: tuple[tuple[int, int], ...],
        projection: planet.Projection,
        *,
        counters: finalize._ProjectionCounters | None = None,
    ) -> finalize.ProjectionFailure:
        if counters is not None:
            counters.collider_pairs += len(pairs)
        return finalize.ProjectionFailure(
            "geom.collide",
            (0, 1),
            "synthetic polar refusal",
            projection.band.area_segments,
        )

    monkeypatch.setattr(finalize, "_projected_static_failure", reject)
    with pytest.raises(finalize.ProjectionRefusal):
        finalize.finalize_placement(placement, policy)


def test_projection_refusal_preserves_order_deduplicates_and_formats_evidence() -> None:
    first = finalize.ProjectionFailure("geom.collide", (4, 5), "overlap", 40)
    second = finalize.ProjectionFailure("game.inserter_paste", (9,), "too close", 60)

    refusal = finalize.ProjectionRefusal((second, first, second))

    assert refusal.failures == (second, first)
    assert refusal.checks == ("game.inserter_paste", "geom.collide")
    assert "band 60" in str(refusal)
    assert "(9,)" in str(refusal)
    assert "too close" in str(refusal)


def test_projection_collects_simultaneous_rule_category_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordered_checks = (
        "game.power_too_close",
        "game.inserter_paste",
        "geom.collide",
        "game.addon_supply",
        "game.addon_splitter_clearance",
    )

    def refusing(check: str) -> object:
        def predicate(
            *args: object,
            counters: finalize._ProjectionCounters | None = None,
        ) -> finalize.ProjectionFailure:
            del counters
            projection = cast(planet.Projection, args[-1])
            return finalize.ProjectionFailure(
                check=check,
                buildings=(0,),
                detail=f"simultaneous {check}",
                band=projection.band.area_segments,
            )

        return predicate

    for name, check in zip(
        (
            "projected_power_failure",
            "_projected_sorter_failure",
            "_projected_static_failure",
            "_projected_addon_failure",
            "_projected_addon_splitter_failure",
        ),
        ordered_checks,
        strict=True,
    ):
        monkeypatch.setattr(finalize, name, refusing(check))

    with pytest.raises(finalize.ProjectionRefusal) as caught:
        finalize.finalize_placement(
            Placement(buildings=_extent(20, 5)),
            BandPolicy("4"),
        )

    assert tuple(failure.check for failure in caught.value.failures) == ordered_checks
    assert caught.value.checks == tuple(sorted(ordered_checks))


def test_projection_counters_count_only_observed_rule_loop_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    building = _building(catalog.TESLA_TOWER_ID, 0, 0)
    node = rules.PowerNode(
        is_power_node=True,
        is_accumulator=False,
        wind_forced_power=False,
        geothermal=False,
    )
    sorter = planet.Sorter(
        x=0.0,
        y=0.0,
        z=0.0,
        x2=1.0,
        y2=0.0,
        z2=0.0,
        yaw=90.0,
        yaw2=90.0,
        input_belt=True,
        output_belt=True,
        ref_x=0.5,
        ref_y=0.0,
        ref_z=0.0,
    )
    placed = colliders.Placed(building.model_index, 0.0, 0.0, 0.0, 0.0)
    invariants = finalize._ProjectionInvariants(
        tested=((0, placed), (1, placed), (2, placed)),
        nodes=((0, building, node), (1, building, node), (2, building, node)),
        sorters=((3, sorter), (4, sorter)),
        belts=(),
        addons=(),
        coaters=(),
        splitters=(),
    )
    pairs = ((0, 1), (0, 2), (1, 2))
    power_work: list[int] = []
    sorter_work: list[int] = []
    collider_work: list[int] = []

    monkeypatch.setattr(finalize, "_projection_invariants", lambda _placement: invariants)
    monkeypatch.setattr(
        planet,
        "candidate_pairs",
        lambda *_args: list(pairs),
    )

    def observed_power(
        _nodes: object,
        projection: planet.Projection,
        *,
        counters: finalize._ProjectionCounters | None = None,
    ) -> finalize.ProjectionFailure | None:
        work = 1 if not power_work else len(pairs)
        power_work.append(work)
        if counters is not None:
            counters.power_pairs += work
        if len(power_work) == 1:
            return finalize.ProjectionFailure(
                "game.power_too_close",
                (0, 1),
                "first pair refused",
                projection.band.area_segments,
            )
        return None

    def observed_sorters(
        _sorters: object,
        projection: planet.Projection,
        *,
        counters: finalize._ProjectionCounters | None = None,
    ) -> finalize.ProjectionFailure | None:
        work = 1 if not sorter_work else len(invariants.sorters)
        sorter_work.append(work)
        if counters is not None:
            counters.sorters += work
        if len(sorter_work) == 1:
            return finalize.ProjectionFailure(
                "game.inserter_paste",
                (3,),
                "first sorter refused",
                projection.band.area_segments,
            )
        return None

    def observed_static(
        _tested: object,
        tested_pairs: tuple[tuple[int, int], ...],
        _projection: planet.Projection,
        *,
        counters: finalize._ProjectionCounters | None = None,
    ) -> None:
        collider_work.append(len(tested_pairs))
        if counters is not None:
            counters.collider_pairs += len(tested_pairs)

    monkeypatch.setattr(finalize, "projected_power_failure", observed_power)
    monkeypatch.setattr(finalize, "_projected_sorter_failure", observed_sorters)
    monkeypatch.setattr(finalize, "_projected_static_failure", observed_static)

    frame = AreaFrame(1, 1, 4, (4,), False)
    counters = finalize._ProjectionCounters()
    failures = finalize._certify_frame(
        Placement(buildings=_extent(1, 1), frame=frame),
        frame,
        counters,
    )

    assert failures
    assert counters.power_pairs == sum(power_work)
    assert counters.sorters == sum(sorter_work)
    assert counters.collider_pairs == sum(collider_work)


@pytest.mark.parametrize(
    ("belt_x", "expected_check"),
    ((0, None), (1, "game.addon_supply")),
)
def test_projected_addon_supply_preserves_strict_radius_boundary(
    belt_x: int,
    expected_check: str | None,
) -> None:
    class FlatProjection:
        band = next(
            candidate for candidate in planet.bands() if candidate.area_segments == 4
        )

        def position(self, x: float, y: float, z: float) -> tuple[float, float, float]:
            return (x, y, z)

    coater = _building(catalog.SPRAY_COATER_ID, 0, 0)
    area = catalog.AddonSupplyPose(Fraction(), Fraction(), Fraction(), area=0)
    failure = finalize._projected_addon_failure(
        ((0, _belt(belt_x, 0, output=None)),),
        ((1, coater, (area,)),),
        cast(planet.Projection, FlatProjection()),
    )

    assert (None if failure is None else failure.check) == expected_check


def test_projected_addon_supply_projects_each_belt_once_per_projection() -> None:
    class CountingFlatProjection:
        band = next(
            candidate for candidate in planet.bands() if candidate.area_segments == 4
        )

        def __init__(self) -> None:
            self.calls = 0

        def position(self, x: float, y: float, z: float) -> tuple[float, float, float]:
            self.calls += 1
            return (x, y, z)

    projection = CountingFlatProjection()
    coater = _building(catalog.SPRAY_COATER_ID, 0, 0)
    areas = catalog.building(catalog.SPRAY_COATER_ID).addon_areas
    belts = (
        (0, _belt(0, 0, output=None)),
        (1, replace(_belt(0, -1, output=None), z=Fraction(1))),
        (2, _belt(20, 20, output=None)),
    )

    assert (
        finalize._projected_addon_failure(
            belts,
            ((3, coater, areas),),
            cast(planet.Projection, projection),
        )
        is None
    )
    assert projection.calls == len(belts) + len(areas)


def test_projection_cache_reuses_only_invariant_frame_work() -> None:
    placement = Placement(
        buildings=_extent(1, 1),
        frame=AreaFrame(1, 1, 4, (4,), False),
    )
    counters = finalize._ProjectionCounters()
    cache = finalize._ProjectionCache(counters)
    frame = placement.frame
    assert frame is not None

    assert finalize._certify_frame(
        placement,
        frame,
        counters,
        cache=cache,
    ) == ()
    first_projection_count = counters.projections
    assert finalize._certify_frame(
        placement,
        frame,
        counters,
        cache=cache,
    ) == ()

    assert counters.invariant_cache_hits == 1
    assert counters.pair_cache_hits == 1
    assert counters.projection_cache_hits == first_projection_count


def test_projection_result_cache_reuses_only_complete_exact_check_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    building = _building(2302, 0, 0)
    placed = colliders.Placed(building.model_index, 0.0, 0.0, 0.0, 0.0)
    sorter = planet.Sorter(
        x=0.0,
        y=0.0,
        z=0.0,
        x2=1.0,
        y2=0.0,
        z2=0.0,
        yaw=90.0,
        yaw2=90.0,
        input_belt=True,
        output_belt=True,
        ref_x=0.5,
        ref_y=0.0,
        ref_z=0.0,
    )
    invariants = finalize._ProjectionInvariants(
        tested=((0, placed), (1, placed)),
        nodes=(),
        sorters=((2, sorter),),
        belts=(),
        addons=(),
        coaters=(),
        splitters=(),
    )
    calls = {
        "power": 0,
        "sorter": 0,
        "static": 0,
        "addon": 0,
        "addon_splitter": 0,
    }

    def observed(name: str) -> object:
        def predicate(*args: object, **kwargs: object) -> None:
            calls[name] += 1

        return predicate

    monkeypatch.setattr(finalize, "projected_power_failure", observed("power"))
    monkeypatch.setattr(finalize, "_projected_sorter_failure", observed("sorter"))
    monkeypatch.setattr(finalize, "_projected_static_failure", observed("static"))
    monkeypatch.setattr(finalize, "_projected_addon_failure", observed("addon"))
    monkeypatch.setattr(
        finalize,
        "_projected_addon_splitter_failure",
        observed("addon_splitter"),
    )
    band = next(candidate for candidate in planet.bands() if candidate.area_segments == 4)
    first = planet.Projection(
        band,
        0,
        colliders.PLANET_SEGMENT,
        colliders.PLANET_RADIUS,
    )
    second = planet.Projection(
        band,
        1,
        colliders.PLANET_SEGMENT,
        colliders.PLANET_RADIUS,
    )
    counters = finalize._ProjectionCounters()
    cache = finalize._ProjectionCache(counters)
    pairs = ((0, 1),)

    assert finalize._failure_at_projection(
        invariants,
        pairs,
        first,
        counters,
        cache=cache,
    ) == ()
    assert finalize._failure_at_projection(
        invariants,
        pairs,
        first,
        counters,
        cache=cache,
    ) == ()
    assert calls == {
        "power": 1,
        "sorter": 1,
        "static": 1,
        "addon": 1,
        "addon_splitter": 1,
    }
    assert counters.power_result_cache_hits == 1
    assert counters.sorter_result_cache_hits == 1
    assert counters.static_result_cache_hits == 1
    assert counters.addon_result_cache_hits == 1
    assert counters.addon_splitter_result_cache_hits == 1

    assert finalize._failure_at_projection(
        invariants,
        pairs,
        second,
        counters,
        cache=cache,
    ) == ()
    assert calls == {
        "power": 2,
        "sorter": 2,
        "static": 2,
        "addon": 2,
        "addon_splitter": 2,
    }



def test_framed_finalization_is_idempotent_only_for_coherent_policy() -> None:
    placement = Placement(buildings=_extent(2, 2))
    policy = BandPolicy("portable")
    finalized = finalize.finalize_placement(placement, policy)

    assert finalize.finalize_placement(finalized, policy) is finalized

    invalid = replace(finalized, frame=AreaFrame(1, 1, 4, (4, 8, 16), False))
    repaired = finalize.finalize_placement(invalid, policy)
    assert repaired is not invalid
    assert repaired.frame == AreaFrame(2, 2, 4, (4, 8, 16), False)



def test_freeform_uses_shared_planet_finalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout.freeform import FreeformLayout

    calls: list[tuple[Placement, BandPolicy]] = []
    original = finalize.finalize_placement
    policy = BandPolicy("portable")

    def observed(
        placement: Placement,
        band_policy: BandPolicy,
    ) -> Placement:
        calls.append((placement, band_policy))
        return original(placement, band_policy)

    monkeypatch.setattr(
        "flab2bp.layout.freeform.finalize.finalize_placement",
        observed,
    )
    placement = FreeformLayout(band_policy=policy, power=False).lay_out(
        two_stage_spec(),
        time_budget_s=0.5,
    )

    assert calls and all(band_policy is policy for _, band_policy in calls)
    assert placement.frame is not None


def test_sequence_pair_uses_shared_planet_finalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from flab2bp.layout.sequence_solver import SequencePairLayout, SequenceSearchResult

    raw = Placement(buildings=_extent(43, 35))
    calls: list[tuple[Placement, BandPolicy]] = []
    policy = BandPolicy("portable")

    def observed(
        placement: Placement,
        band_policy: BandPolicy,
    ) -> Placement:
        calls.append((placement, band_policy))
        return replace(
            placement,
            frame=AreaFrame(43, 35, 160, (160, 200), False),
        )

    class _Solver:
        def search(
            self,
            *,
            max_stages: int | None = None,
        ) -> SequenceSearchResult:
            del max_stages
            return cast(SequenceSearchResult, SimpleNamespace(placement=raw))

    def factory(*_args: object, **_kwargs: object) -> _Solver:
        return _Solver()

    monkeypatch.setattr(
        "flab2bp.layout.sequence_solver.finalize.finalize_placement",
        observed,
    )
    placement = SequencePairLayout(
        band_policy=policy,
        solver_factory=factory,
    ).lay_out(
        two_stage_spec(),
        time_budget_s=0.5,
    )

    assert calls == [(raw, policy)]
    assert placement.frame == AreaFrame(43, 35, 160, (160, 200), False)
