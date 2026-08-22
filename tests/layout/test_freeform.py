"""Tests for Strategy B -- free-form packing + belt routing.

The specs here are hand-built rather than taken from ``rates/``: this suite must
be able to fail for layout reasons alone, and a dependency on the rate solver
would let a rates regression masquerade as a layout one.
"""

from __future__ import annotations

from fractions import Fraction as F

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout import validate
from flab2bp.layout.base import DETERMINISTIC_WORKERS, PlacedBuilding, Placement
from flab2bp.layout.freeform import (
    MU_DIRECT,
    FreeformLayout,
    _build,
    _direct_net_candidates,
    _pack,
    fallback_placement,
    plan_strips,
    tie_break_cap,
)
from flab2bp.layout.spine import MACHINE_ITEM_IDS
from flab2bp.spec import BuildSpec, MachineGroup, ProliferatorMode

SpecFactory = object


def group(
    recipe: str,
    machine: str,
    count: int,
    inputs: dict[str, F] | None = None,
    outputs: dict[str, F] | None = None,
    *,
    mode: ProliferatorMode = ProliferatorMode.NONE,
) -> MachineGroup:
    return MachineGroup(
        recipe_id=recipe,
        machine_item_id=machine,
        count=count,
        proliferator_mode=mode,
        inputs_per_machine=inputs or {},
        outputs_per_machine=outputs or {},
    )


def single_recipe_spec() -> BuildSpec:
    return BuildSpec(
        groups=(group("iron-ingot", "arc-smelter", 4, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),),
        external_inputs={"iron-ore": F(4)},
        outputs={"iron-ingot": F(4)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="single",
    )


def two_stage_spec() -> BuildSpec:
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 4, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group("gear", "assembling-machine-2", 2, {"iron-ingot": F(1)}, {"gear": F(1)}),
        ),
        external_inputs={"iron-ore": F(4)},
        outputs={"gear": F(2)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="two-stage",
    )


def balanced_pair_spec() -> BuildSpec:
    """Producer and consumer strips of EQUAL width, so stacking is not a penalty.

    Direct insertion needs the consumer stacked under the producer. For two boxes
    of width ``a`` and ``b`` and equal height ``h``, side-by-side costs
    ``(a+b)*h`` and stacked costs ``max(a,b)*2h`` -- identical when ``a == b``,
    and strictly worse for stacking when they differ. ``two_stage_spec`` has
    widths 12 and 6, so side-by-side wins there on area alone and the tie-break
    never gets a say. Equal widths put the decision where this test wants it.
    """
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 4, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group("gear", "assembling-machine-2", 4, {"iron-ingot": F(1)}, {"gear": F(1)}),
        ),
        external_inputs={"iron-ore": F(4)},
        outputs={"gear": F(4)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="balanced-pair",
    )


def magnetic_ring_spec() -> BuildSpec:
    """The calibration spec: 58 machines, 9 groups, 11 internal edges."""
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 12, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group("copper-ingot", "arc-smelter", 4, {"copper-ore": F(1)}, {"copper-ingot": F(1)}),
            group("magnet", "arc-smelter", 17, {"iron-ore": F(1)}, {"magnet": F(1)}),
            group(
                "energetic-graphite", "arc-smelter", 2, {"coal": F(2)}, {"energetic-graphite": F(1)}
            ),
            group(
                "magnetic-coil",
                "assembling-machine-2",
                4,
                {"magnet": F(2), "copper-ingot": F(1)},
                {"magnetic-coil": F(1)},
            ),
            group("gear", "assembling-machine-2", 4, {"iron-ingot": F(1)}, {"gear": F(1)}),
            group(
                "electric-motor",
                "assembling-machine-2",
                8,
                {"iron-ingot": F(1), "gear": F(1), "magnetic-coil": F(1)},
                {"electric-motor": F(1)},
            ),
            group(
                "electromagnetic-turbine",
                "assembling-machine-2",
                4,
                {"electric-motor": F(1), "magnetic-coil": F(1)},
                {"electromagnetic-turbine": F(1)},
            ),
            group(
                "super-magnetic-ring",
                "assembling-machine-2",
                3,
                {
                    "electromagnetic-turbine": F(2),
                    "energetic-graphite": F(1),
                    "magnet": F(3),
                },
                {"super-magnetic-ring": F(1)},
            ),
        ),
        external_inputs={"iron-ore": F(46), "copper-ore": F(8), "coal": F(4)},
        outputs={"super-magnetic-ring": F(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="magnetic-ring",
    )


def proliferated_spec() -> BuildSpec:
    """Every consumer proliferated, so the direct-insert set must be empty."""
    base = two_stage_spec()
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 4, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group(
                "gear",
                "assembling-machine-2",
                2,
                {"iron-ingot": F(1)},
                {"gear": F(1)},
                mode=ProliferatorMode.PRODUCTS,
            ),
        ),
        external_inputs={**base.external_inputs, "proliferator-3": F(1) / 2},
        outputs=base.outputs,
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="proliferated",
        belt_required_edges=frozenset({("iron-ingot", "gear")}),
        spray_lanes={"iron-ingot": False},
    )


ALL_SPECS = [single_recipe_spec, two_stage_spec, magnetic_ring_spec, proliferated_spec]


# --- helpers ---------------------------------------------------------------


def blocking_tiles(p: Placement) -> list[tuple[int, int, int]]:
    """Tiles that genuinely exclude another building.

    Mirrors the validator's occupancy rule: sorters are overlays whose anchors
    sit on the buildings they connect, and belt addons such as the Spray Coater
    consume no grid cell at all.
    """
    tiles: list[tuple[int, int, int]] = []
    for b in p.buildings:
        if catalog.is_sorter(b.item_id):
            continue
        if not catalog.building(b.item_id).occupies_tiles:
            continue
        tiles.extend(b.tiles())
    return tiles


def machines_of(p: Placement) -> list[int]:
    return [
        i
        for i, b in enumerate(p.buildings)
        if not catalog.is_sorter(b.item_id)
        and not catalog.is_belt(b.item_id)
        and b.item_id != catalog.TESLA_TOWER_ID
        and catalog.building(b.item_id).occupies_tiles
    ]


# --- strip planning --------------------------------------------------------


class TestPlanStrips:
    def test_every_machine_lands_in_exactly_one_strip(self) -> None:
        spec = magnetic_ring_spec()
        strips = plan_strips(spec, strip_len=6)
        placed = sum(s.machines for s in strips)
        assert placed == spec.machine_count

    def test_strip_length_is_respected(self) -> None:
        spec = magnetic_ring_spec()
        strips = plan_strips(spec, strip_len=6)
        assert all(s.machines <= 6 for s in strips)

    def test_input_lanes_stay_within_sorter_reach(self) -> None:
        """More input lanes than a sorter can span is unbuildable, not merely tall."""
        for spec_fn in ALL_SPECS:
            for s in plan_strips(spec_fn(), strip_len=6):
                assert len(s.in_lanes) <= catalog.SORTER_MAX_REACH
                assert len(s.out_lanes) <= catalog.SORTER_MAX_REACH

    def test_a_recipe_with_too_many_inputs_is_rejected_not_mangled(self) -> None:
        spec = BuildSpec(
            groups=(
                group(
                    "impossible",
                    "assembling-machine-2",
                    1,
                    {"a": F(1), "b": F(1), "c": F(1), "d": F(1)},
                    {"out": F(1)},
                ),
            )
        )
        with pytest.raises(ValueError, match="input lanes"):
            plan_strips(spec, strip_len=6)


# --- fallback --------------------------------------------------------------


class TestFallback:
    @pytest.mark.parametrize("spec_fn", ALL_SPECS, ids=lambda f: f.__name__)
    def test_fallback_alone_produces_a_valid_placement(self, spec_fn: object) -> None:
        p = fallback_placement(spec_fn(), power=True)  # type: ignore[operator]
        tiles = blocking_tiles(p)
        assert len(tiles) == len(set(tiles)), "fallback overlaps"
        assert p.buildings

    @pytest.mark.parametrize("spec_fn", ALL_SPECS, ids=lambda f: f.__name__)
    def test_fallback_places_every_machine(self, spec_fn: object) -> None:
        spec = spec_fn()  # type: ignore[operator]
        p = fallback_placement(spec, power=True)
        assert len(machines_of(p)) == spec.machine_count


# --- placement properties --------------------------------------------------


@pytest.mark.parametrize("spec_fn", ALL_SPECS, ids=lambda f: f.__name__)
@pytest.mark.parametrize("power", [True, False], ids=["power", "no-power"])
class TestPlacementProperties:
    def test_no_two_blocking_footprints_share_a_tile(
        self, spec_fn: object, power: bool
    ) -> None:
        p = FreeformLayout(power=power).lay_out(spec_fn(), time_budget_s=0.4)  # type: ignore[operator]
        tiles = blocking_tiles(p)
        assert len(tiles) == len(set(tiles)), "overlapping footprints"

    def test_every_machine_is_placed(self, spec_fn: object, power: bool) -> None:
        spec = spec_fn()  # type: ignore[operator]
        p = FreeformLayout(power=power).lay_out(spec, time_budget_s=0.4)
        assert len(machines_of(p)) == spec.machine_count

    def test_every_sorter_is_within_reach_and_single_altitude(
        self, spec_fn: object, power: bool
    ) -> None:
        p = FreeformLayout(power=power).lay_out(spec_fn(), time_budget_s=0.4)  # type: ignore[operator]
        for b in p.buildings:
            if not catalog.is_sorter(b.item_id):
                continue
            assert b.x2 is not None and b.y2 is not None
            dx, dy = abs(b.x - b.x2), abs(b.y - b.y2)
            assert not (dx and dy), "sorters run straight, never diagonally"
            span = dx + dy
            assert 1 <= span <= catalog.SORTER_MAX_REACH, f"span {span}"
            assert b.z == (b.z2 or 0), "sorters never span altitudes"

    def test_sorter_endpoints_reference_distinct_real_buildings(
        self, spec_fn: object, power: bool
    ) -> None:
        p = FreeformLayout(power=power).lay_out(spec_fn(), time_budget_s=0.4)  # type: ignore[operator]
        n = len(p.buildings)
        for b in p.buildings:
            if not catalog.is_sorter(b.item_id):
                continue
            assert b.input_obj is not None and 0 <= b.input_obj < n
            assert b.output_obj is not None and 0 <= b.output_obj < n
            assert b.input_obj != b.output_obj

    def test_belt_links_are_adjacent_and_acyclic(self, spec_fn: object, power: bool) -> None:
        p = FreeformLayout(power=power).lay_out(spec_fn(), time_budget_s=0.4)  # type: ignore[operator]
        bs = p.buildings
        for i, b in enumerate(bs):
            if not catalog.is_belt(b.item_id):
                continue
            o = b.output_obj
            if o is None:
                continue
            assert 0 <= o < len(bs)
            t = bs[o]
            assert abs(t.x - b.x) + abs(t.y - b.y) <= 1, f"belt {i} links non-adjacent"

    def test_validator_reports_no_errors(self, spec_fn: object, power: bool) -> None:
        """The neutral judge is the real acceptance criterion."""
        p = FreeformLayout(power=power).lay_out(spec_fn(), time_budget_s=0.4)  # type: ignore[operator]
        # Declare whether power was requested. The validator will not infer it:
        # treating "no towers" as "power was off" would make a dropped tower
        # indistinguishable from a deliberate --no-power build.
        report = validate.validate(p, expect_power=power)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:10])


# --- the direct-insert / proliferation interaction -------------------------


class TestProliferationForbidsDirectInsertion:
    def test_belt_required_edges_are_never_direct_inserted(self) -> None:
        spec = proliferated_spec()
        layout = FreeformLayout(power=False)
        p = layout.lay_out(spec, time_budget_s=0.4)
        assert p.stats["direct_inserts"] == 0.0

    def test_an_unproliferated_twin_permits_direct_insertion(self) -> None:
        """Guards the constraint against being vacuous.

        If the same spec without proliferation also reported zero candidates,
        the previous test would prove nothing about the constraint.
        """
        layout = FreeformLayout(power=False)
        p = layout.lay_out(two_stage_spec(), time_budget_s=0.4)
        assert p.stats["direct_insert_candidates"] > 0.0

    def test_the_proliferated_spec_still_validates(self) -> None:
        """A silently under-producing build pastes cleanly, so the judge matters."""
        p = FreeformLayout(power=False).lay_out(proliferated_spec(), time_budget_s=0.4)
        report = validate.validate(p, expect_power=False)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:5])


# --- direct insertion ------------------------------------------------------


class TestDirectInsertion:
    """A direct insert replaces a routed belt net with a single sorter.

    These tests exist because the feature was previously *identified* and then
    discarded -- ``stats["direct_inserts"]`` was hardcoded to zero and the
    ``MU_DIRECT`` reward never reached the objective. Asserting the counter moved
    would not have caught that; asserting belts disappear does.
    """

    @staticmethod
    def _stacked(spec: BuildSpec, *, direct: bool) -> tuple[Placement, object]:
        """Pack at a height that forces stacking, then build.

        Deliberately below `lay_out`, because the full height sweep is area-first
        and stacking *costs* area here -- see
        ``test_the_sweep_prefers_area_over_direct_insertion``. Testing through the
        sweep would therefore assert the mechanism is broken when it is merely
        outranked. This exercises the mechanism itself.
        """
        strips = plan_strips(spec, strip_len=6)
        cands = _direct_net_candidates(strips, spec) if direct else {}
        height = sum(s.height + 1 for s in strips)
        pack = _pack(
            strips,
            height=height,
            width_bound=max(s.width + 1 for s in strips) * 2,
            time_budget_s=1.0,
            direct_candidates=cands,
            workers=DETERMINISTIC_WORKERS,
        )
        assert pack is not None
        placement, _failed, _towers = _build(spec, strips, pack, power=False, route=True)
        return placement, pack

    def test_an_adjacent_pair_is_actually_direct_inserted(self) -> None:
        p, pack = self._stacked(balanced_pair_spec(), direct=True)
        assert pack.direct, "packer found no direct-insertable pair"  # type: ignore[attr-defined]
        assert p.stats["direct_inserts"] >= 1.0

    def test_direct_insertion_removes_belts_rather_than_only_counting(self) -> None:
        """The mechanism, not the counter.

        Same spec, same height, same worker count -- the only difference is
        whether direct insertion is permitted. If enabling it does not delete
        belt tiles then no net was actually replaced, which is precisely the bug
        this feature previously had: a hardcoded counter and no effect.
        """
        spec = balanced_pair_spec()
        on, _ = self._stacked(spec, direct=True)
        off, _ = self._stacked(spec, direct=False)

        assert off.stats["direct_inserts"] == 0.0
        assert on.stats["direct_inserts"] >= 1.0
        assert on.stats["nets"] < off.stats["nets"], "a direct insert must delete a net"
        assert on.stats["belt_tiles"] < off.stats["belt_tiles"], (
            f"direct insertion kept {on.stats['belt_tiles']:.0f} belt tiles versus "
            f"{off.stats['belt_tiles']:.0f} without it"
        )

    def test_a_direct_inserted_pair_still_validates(self) -> None:
        p, _ = self._stacked(balanced_pair_spec(), direct=True)
        assert p.stats["direct_inserts"] >= 1.0
        report = validate.validate(p, expect_power=False)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:5])

    def test_direct_insert_sorters_obey_reach_and_stay_on_one_level(self) -> None:
        p, _ = self._stacked(balanced_pair_spec(), direct=True)
        assert p.stats["direct_inserts"] >= 1.0
        for b in p.buildings:
            if not catalog.is_sorter(b.item_id):
                continue
            assert b.x2 is not None and b.y2 is not None
            span = abs(b.x - b.x2) + abs(b.y - b.y2)
            assert 1 <= span <= catalog.SORTER_MAX_REACH
            assert b.z == (b.z2 or 0), "sorters never span altitudes"

    def test_the_sweep_prefers_area_over_direct_insertion(self) -> None:
        """Pins the measured trade-off, so a later change has to argue with it.

        Direct insertion needs the consumer stacked under the producer, and
        stacking pays MARGIN vertically between the two strips. On the balanced
        pair that is 132 tiles with the direct insert against 125 without, for a
        saving of 5 belt tiles. Area is the bake-off metric and it wins.

        This is the honest ceiling on the feature as built: it replaces a routed
        net with a sorter, but it does NOT delete the two lanes the sorter spans,
        so it cannot pay for the row it costs. Deleting those lanes is the
        structural change that would make it a real density lever.
        """
        spec = balanced_pair_spec()
        kw = {"power": False, "workers": DETERMINISTIC_WORKERS}
        swept = FreeformLayout(direct_insert=True, **kw).lay_out(spec, time_budget_s=0.8)  # type: ignore[arg-type]
        stacked, _ = self._stacked(spec, direct=True)

        assert stacked.stats["direct_inserts"] >= 1.0
        assert swept.area <= stacked.area, "the sweep must not choose a larger pack"
        assert swept.stats["belt_tiles"] >= stacked.stats["belt_tiles"], (
            "the cheaper-area pack is expected to carry MORE belts, which is the "
            "trade being made"
        )


class TestObjectiveStaysLexicographic:
    """Width must outrank the tie-break tier absolutely.

    Blending them is what made *more* solver time produce *worse* area, since the
    blended proxy was anti-correlated with the metric actually reported. The
    direct-insert reward joins the tie-break tier, so the cap has to grow with it
    or the property silently lapses.
    """

    @pytest.mark.parametrize(
        ("n_terms", "width_bound", "height", "n_direct"),
        [(0, 8, 8, 0), (22, 64, 40, 11), (2, 4, 4, 1), (100, 500, 300, 250)],
    )
    def test_one_tile_of_width_outranks_the_entire_tie_break_tier(
        self, n_terms: int, width_bound: int, height: int, n_direct: int
    ) -> None:
        cap = tie_break_cap(n_terms, width_bound=width_bound, height=height, n_direct=n_direct)
        worst = n_terms * (width_bound + height) + MU_DIRECT * n_direct
        assert cap > worst, "a width saving must beat every possible tie-break saving"

    def test_the_cap_accounts_for_the_direct_insert_reward(self) -> None:
        """A cap ignoring direct inserts would let them buy width. Pin that."""
        without = tie_break_cap(4, width_bound=20, height=10, n_direct=0)
        with_di = tie_break_cap(4, width_bound=20, height=10, n_direct=7)
        assert with_di > without
        assert with_di - without == MU_DIRECT * 7


# --- solver quality --------------------------------------------------------


class TestSolverActuallyRuns:
    def test_solved_path_beats_the_fallback(self) -> None:
        """The failure Strategy A shipped: a fallback wearing a solver's clothes.

        A bake-off comparing two fallbacks is worse than useless, so this asserts
        the solved path is genuinely exercised and genuinely better.
        """
        spec = magnetic_ring_spec()
        solved = FreeformLayout(power=True).lay_out(spec, time_budget_s=10.0)
        fallback = fallback_placement(spec, power=True)
        assert solved.stats["fallback_used"] == 0.0, "solver silently fell back"
        assert solved.area < fallback.area, (
            f"solved {solved.area} did not beat fallback {fallback.area}"
        )

    def test_failures_are_recorded_never_swallowed(self) -> None:
        p = FreeformLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=10.0)
        for key in ("fallback_used", "route_failures", "repair_iterations", "solver_status"):
            assert key in p.stats

    def test_zero_budget_falls_back_and_says_so(self) -> None:
        p = FreeformLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=0.0)
        assert p.stats["fallback_used"] == 1.0

    def test_deterministic_for_a_fixed_budget(self) -> None:
        """Reproducibility is the property under test here, so pin workers.

        The shipping default is multi-worker, which is deliberately
        nondeterministic -- CP-SAT runs a portfolio and takes whichever
        strategy wins. That is worth 23% density, so the bake-off keeps it
        and absorbs the variance by repeating cells. This test pins
        DETERMINISTIC_WORKERS because it asserts run-to-run identity.
        """
        spec = two_stage_spec()
        w = DETERMINISTIC_WORKERS
        a = FreeformLayout(power=True, workers=w).lay_out(spec, time_budget_s=0.4)
        b = FreeformLayout(power=True, workers=w).lay_out(spec, time_budget_s=0.4)
        assert a.area == b.area
        assert len(a.buildings) == len(b.buildings)


# --- power -----------------------------------------------------------------


class TestPower:
    def test_towers_appear_only_when_power_is_on(self) -> None:
        spec = two_stage_spec()
        on = FreeformLayout(power=True).lay_out(spec, time_budget_s=0.4)
        off = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.4)
        assert on.stats["towers"] > 0
        assert off.stats["towers"] == 0

    def test_every_powered_building_is_covered(self) -> None:
        p = FreeformLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        report = validate.validate(p, only=["power.coverage", "power.connectivity"])
        assert report.ok, "\n".join(f.message for f in report.errors[:5])

    def test_coverage_check_can_actually_fail(self) -> None:
        """A power check that cannot fail would silently bless a dark factory.

        The failing case has to be a tower that does not *reach*, not a
        placement with no towers at all.  "No towers" is what ``--no-power``
        legitimately produces, and flagging it buried real findings under one
        error per machine.  Here a single tower sits far outside its own 10.5
        supply radius of the assembler, which is a genuine defect.
        """
        assembler = catalog.building(MACHINE_ITEM_IDS["assembling-machine-2"])
        tower = catalog.building(catalog.TESLA_TOWER_ID)
        far = int(catalog.TESLA_COVER_RADIUS) + 20
        p = Placement(
            buildings=(
                PlacedBuilding(
                    item_id=assembler.item_id,
                    model_index=assembler.model_index,
                    x=0,
                    y=0,
                    width=assembler.width,
                    height=assembler.height,
                ),
                PlacedBuilding(
                    item_id=tower.item_id,
                    model_index=tower.model_index,
                    x=far,
                    y=far,
                    width=tower.width,
                    height=tower.height,
                ),
            )
        )
        report = validate.validate(p, only=["power.coverage"])
        assert not report.ok, "a tower 30 tiles away must not count as covering"

    def test_coverage_is_skipped_rather_than_failed_when_power_is_off(self) -> None:
        """``--no-power`` is a legitimate mode, not a factory-wide error."""
        p = FreeformLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.4)
        assert p.stats["towers"] == 0
        report = validate.validate(p, only=["power.coverage"], expect_power=False)
        assert not report.findings
        assert "power.coverage" in report.skipped


# --- exact arithmetic ------------------------------------------------------


class TestNoFloatEntersCapacityDecisions:
    def test_lane_counts_are_computed_from_exact_fractions(self) -> None:
        from flab2bp.layout.freeform import lanes_for

        # 25/s over a 12/s belt needs 3 lanes; 24/s needs exactly 2, and a float
        # 24.000000001 would wrongly demand 3.
        assert lanes_for(F(25), F(12)) == 3
        assert lanes_for(F(24), F(12)) == 2
        assert lanes_for(F(1, 3), F(12)) == 1

    def test_zero_rate_needs_no_lane(self) -> None:
        from flab2bp.layout.freeform import lanes_for

        assert lanes_for(F(0), F(12)) == 0
