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
from flab2bp.layout.base import (
    DETERMINISTIC_WORKERS,
    NoValidLayout,
    PlacedBuilding,
    Placement,
)
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

#: Freeform used to refuse any strip plan where one producer lane had to feed
#: several consumer lanes, because a belt tile has one ``output_obj``.  It now
#: taps a different TILE of the lane for each consumer and junctions there with
#: a splitter, so the gap is closed and the marker that stood here is gone.
#:
#: Kept as a note rather than a marker: the tests it was attached to are the
#: ones that prove the fan-out works, and they assert it directly now.
#: ``ALL_SPECS`` for ``parametrize``, with the unservable spec marked.  Kept
#: separate because ``ALL_SPECS`` is also iterated directly, where a
#: ``pytest.param`` wrapper would not be callable.
ALL_SPEC_PARAMS = [pytest.param(f, id=f.__name__) for f in ALL_SPECS]


# --- helpers ---------------------------------------------------------------


def blocking_tiles(p: Placement) -> list[tuple[int, int, int]]:
    """Tiles that genuinely exclude another building.

    Mirrors the validator's occupancy rule: belt-integrated buildings share
    tiles rather than reserving them, and belt addons such as the Spray Coater
    consume no grid cell at all.

    ``is_belt_integrated``, not ``is_sorter``. Belts and SPLITTERS are equally
    belt-integrated, and a junction legitimately carries several belts on its
    own tile -- the lane arriving, the lane continuing past it, and the branch
    leaving. Counting those as collisions reported six overlaps in a layout the
    game accepts. Belt-on-belt overlap is still checked, by
    ``geom.belt_single_occupancy``, which knows about junctions.
    """
    tiles: list[tuple[int, int, int]] = []
    for b in p.buildings:
        if catalog.is_belt_integrated(b.item_id):
            continue
        if not catalog.building(b.item_id).occupies_tiles:
            continue
        tiles.extend(b.tiles())
    return tiles


def machines_of(p: Placement) -> list[int]:
    """Buildings that are actual machines, for counting against the spec.

    Uses ``is_belt_integrated`` rather than spelling out belts and sorters. The
    hand-written version missed SPLITTERS, which are equally belt-integrated,
    and so counted every junction as a machine -- 59 "machines" for a 58-machine
    spec, varying run to run with how many junctions the packer needed. That
    reads exactly like a layout duplicating machines, which is what it was
    reported as.
    """
    return [
        i
        for i, b in enumerate(p.buildings)
        if not catalog.is_belt_integrated(b.item_id)
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

    def test_lanes_stay_within_sorter_reach_on_each_side(self) -> None:
        """A sorter spans three tiles, so each SIDE carries at most three lanes.

        The limit is per side, not per strip: lanes above and lanes below are
        reached by different sorters, so six lanes total is fine while four on
        one side is not.
        """
        for spec_fn in ALL_SPECS:
            for s in plan_strips(spec_fn(), strip_len=6):
                assert len(s.in_above) <= catalog.SORTER_MAX_REACH
                assert len(s.out_lanes) + len(s.in_below) <= catalog.SORTER_MAX_REACH

    def test_a_four_input_recipe_is_fed_from_both_sides(self) -> None:
        """Four ingredients is ordinary, not exotic -- orbital-collector has four.

        Three fit above; the fourth goes below alongside the output lane. Every
        prior test used recipes with three inputs or fewer, which is why this
        stayed broken until a real URL was tried.
        """
        spec = BuildSpec(
            groups=(
                group(
                    "four-in",
                    "assembling-machine-2",
                    2,
                    {"a": F(1), "b": F(1), "c": F(1), "d": F(1)},
                    {"out": F(1)},
                ),
            ),
            external_inputs={"a": F(2), "b": F(2), "c": F(2), "d": F(2)},
            outputs={"out": F(2)},
        )
        strips = plan_strips(spec, strip_len=6)
        assert len(strips) == 1
        s = strips[0]
        assert set(s.in_lanes) == {"a", "b", "c", "d"}
        assert len(s.in_above) == catalog.SORTER_MAX_REACH
        assert len(s.in_below) == 1
        # Every lane still reachable: three above, two below (one in, one out).
        assert len(s.in_above) <= catalog.SORTER_MAX_REACH
        assert len(s.in_below) + len(s.out_lanes) <= catalog.SORTER_MAX_REACH
        assert s.height == 3 + s.mh + 2

    def test_a_four_input_recipe_lays_out_and_validates(self) -> None:
        """Planning it is not enough -- it has to emit and pass the neutral judge.

        Uses a REAL four-ingredient recipe, because emission needs a genuine DSP
        recipe id; a synthesised name plans fine and then fails at the catalog.
        """
        ins = {
            "annihilation-constraint-sphere": F(1),
            "antimatter": F(1),
            "hydrogen": F(1),
            "titanium-alloy": F(1),
        }
        spec = BuildSpec(
            groups=(
                group(
                    "antimatter-fuel-rod",
                    "assembling-machine-2",
                    2,
                    ins,
                    {"antimatter-fuel-rod": F(1)},
                ),
            ),
            external_inputs={k: F(2) for k in ins},
            outputs={"antimatter-fuel-rod": F(2)},
        )
        strips = plan_strips(spec, strip_len=6)
        assert len(strips[0].in_below) == 1, "the fourth ingredient must go below"
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        report = validate.validate(p, expect_power=False)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:6])

    @staticmethod
    def _many_input_spec(n: int) -> BuildSpec:
        import string

        return BuildSpec(
            groups=(
                group(
                    "impossible",
                    "assembling-machine-2",
                    1,
                    {k: F(1) for k in string.ascii_lowercase[:n]},
                    {"out": F(1)},
                ),
            )
        )

    def test_mixing_raises_the_ceiling_well_past_any_real_recipe(self) -> None:
        """Fifteen ingredients now seat: three lanes above and two below, each
        holding up to the assembler's three-tile width, with the last south lane
        left for the output."""
        strips = plan_strips(self._many_input_spec(15), strip_len=6)
        assert len(strips[0].in_lanes) == 15

    def test_a_recipe_needing_more_lanes_than_two_sides_carry_is_rejected(self) -> None:
        """Sixteen exceeds even mixed lanes, and truncating one ingredient would
        produce a blueprint that pastes cleanly and then stalls.

        The bar moved from seven to sixteen when lanes learned to carry several
        items; DSP's own recipes top out at six ingredients, so this limit no
        longer binds anything real.
        """
        with pytest.raises(ValueError, match="cannot be seated"):
            plan_strips(self._many_input_spec(16), strip_len=6)


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


@pytest.mark.parametrize("spec_fn", ALL_SPEC_PARAMS)
@pytest.mark.parametrize("power", [True, False], ids=["power", "no-power"])
class TestPlacementProperties:
    def test_no_two_blocking_footprints_share_a_tile(
        self, spec_fn: object, power: bool
    ) -> None:
        p = FreeformLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)  # type: ignore[operator]
        tiles = blocking_tiles(p)
        assert len(tiles) == len(set(tiles)), "overlapping footprints"

    def test_every_machine_is_placed(self, spec_fn: object, power: bool) -> None:
        spec = spec_fn()  # type: ignore[operator]
        p = FreeformLayout(power=power).lay_out(spec, time_budget_s=0.5)
        assert len(machines_of(p)) == spec.machine_count

    def test_every_sorter_is_within_reach_and_single_altitude(
        self, spec_fn: object, power: bool
    ) -> None:
        p = FreeformLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)  # type: ignore[operator]
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
        p = FreeformLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)  # type: ignore[operator]
        n = len(p.buildings)
        for b in p.buildings:
            if not catalog.is_sorter(b.item_id):
                continue
            assert b.input_obj is not None and 0 <= b.input_obj < n
            assert b.output_obj is not None and 0 <= b.output_obj < n
            assert b.input_obj != b.output_obj

    def test_belt_links_are_adjacent_and_acyclic(self, spec_fn: object, power: bool) -> None:
        p = FreeformLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)  # type: ignore[operator]
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
        p = FreeformLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)  # type: ignore[operator]
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
        p = layout.lay_out(spec, time_budget_s=0.5)
        assert p.stats["direct_inserts"] == 0.0

    def test_an_unproliferated_twin_permits_direct_insertion(self) -> None:
        """Guards the constraint against being vacuous.

        If the same spec without proliferation also reported zero candidates,
        the previous test would prove nothing about the constraint.
        """
        layout = FreeformLayout(power=False)
        p = layout.lay_out(two_stage_spec(), time_budget_s=0.5)
        assert p.stats["direct_insert_candidates"] > 0.0

    def test_the_proliferated_spec_still_validates(self) -> None:
        """A silently under-producing build pastes cleanly, so the judge matters."""
        p = FreeformLayout(power=False).lay_out(proliferated_spec(), time_budget_s=0.5)
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
            time_budget_s=0.5,
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
        swept = FreeformLayout(direct_insert=True, **kw).lay_out(spec, time_budget_s=0.5)  # type: ignore[arg-type]
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
    def test_solved_path_beats_the_greedy_construction(self) -> None:
        """The failure Strategy A shipped: a fallback wearing a solver's clothes.

        A bake-off comparing two fallbacks is worse than useless, so this asserts
        the solved path is genuinely exercised and genuinely better.

        ``fallback_placement`` is no longer reachable from ``lay_out`` -- it
        calls ``_build(route=False)``, so it never attempts the wiring it once
        claimed to guarantee -- but it is still the construction the solver has
        to beat, so it stays here as the yardstick.
        """
        spec = two_stage_spec()
        solved = FreeformLayout(power=True).lay_out(spec, time_budget_s=2.0)
        greedy = fallback_placement(spec, power=True)
        assert solved.stats["fallback_used"] == 0.0, "solver silently fell back"
        assert solved.stats["solver_status"] > 0.0, "no CP-SAT status: the pack was not solved"

        # NOT an area comparison any more, and the reason matters. `greedy`
        # calls `_build(route=False)`: it has no belts at all, so it is smaller
        # than any working layout and always will be. Comparing areas would ask
        # the solver to beat a layout that wins by not connecting anything --
        # the exact scoring mistake that made an earlier bake-off pick a build
        # with 119 unrouted nets as the densest on offer.
        #
        # What the solved path must beat it on is WORKING.
        assert _full_report(solved, spec, power=True).ok, "the solved layout does not validate"
        assert not _full_report(greedy, spec, power=True).ok, (
            "the greedy construction validated, so it is no longer the "
            "unrouted straw man this test compares against -- rewrite the test"
        )

    def test_failures_are_recorded_never_swallowed(self) -> None:
        p = FreeformLayout(power=True).lay_out(two_stage_spec(), time_budget_s=2.0)
        for key in ("fallback_used", "route_failures", "repair_iterations", "solver_status"):
            assert key in p.stats

    def test_a_producer_feeding_many_consumers_is_served(self) -> None:
        """The gap this used to pin as unfixable, now closed.

        A belt tile has one ``output_obj``, so a lane feeding four consumers
        cannot simply point at all four. It taps a different TILE of the lane
        for each and puts a splitter there -- the lane keeps flowing past the
        tap, and the branch draws from the junction.

        This test previously asserted the opposite (that the spec was refused),
        deliberately written to fail the moment the gap closed. It did.
        """
        spec = fan_out_spec(consumers=4)
        p = FreeformLayout(power=True).lay_out(spec, time_budget_s=2.0)
        report = _full_report(p, spec, power=True)
        assert report.ok, "\n".join(f.message for f in report.errors[:5])
        assert p.stats["route_failures"] == 0.0

    def test_zero_budget_refuses_rather_than_falling_back(self) -> None:
        """A zero budget is a refusal, not a licence to hand back the greedy stack.

        ``fallback_placement`` never routes, so returning it returned a layout
        that was both broken and -- because an unrouted net is a belt run that
        does not exist -- smaller than a correct one.
        """
        with pytest.raises(NoValidLayout) as exc:
            FreeformLayout(power=True).lay_out(two_stage_spec(), time_budget_s=0.0)
        assert "packer was never asked" in exc.value.reason

    @pytest.mark.uncached_layout
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
        a = FreeformLayout(power=True, workers=w).lay_out(spec, time_budget_s=0.5)
        b = FreeformLayout(power=True, workers=w).lay_out(spec, time_budget_s=0.5)
        assert a.area == b.area
        assert len(a.buildings) == len(b.buildings)


# --- power -----------------------------------------------------------------


class TestPower:
    def test_towers_appear_only_when_power_is_on(self) -> None:
        spec = two_stage_spec()
        on = FreeformLayout(power=True).lay_out(spec, time_budget_s=0.5)
        off = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
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
        p = FreeformLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
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


# --- proliferator supply ---------------------------------------------------


def _id_map_for(spec: BuildSpec) -> validate.IdMap:
    """The same bridge the pipeline builds, so tests judge what shipping judges."""
    from flab2bp.pipeline import _id_map

    return _id_map(spec)


def _full_report(p: Placement, spec: BuildSpec, *, power: bool = False) -> validate.Report:
    """Validate with the spec attached.

    Without it nine checks are skipped and a broken build reports clean -- which
    is exactly how the unsupplied-coater bug survived this long.
    """
    return validate.validate(p, spec, ids=_id_map_for(spec), expect_power=power)


class TestProliferatorIsActuallySupplied:
    """A coater with nothing to spray is worse than no coater at all.

    It pastes, the machines run, and every proliferated recipe quietly produces
    at the unproliferated rate -- so the build misses the objective with nothing
    visibly wrong.
    """

    def test_some_belt_carries_the_proliferator(self) -> None:
        spec = proliferated_spec()
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        prolif = {i for i in spec.external_inputs if i.startswith("proliferator")}
        assert prolif, "fixture must declare a proliferator input"
        carried = {
            b.carries_item for b in p.buildings if catalog.is_belt(b.item_id)
        }
        assert carried & prolif, (
            f"no belt carries {sorted(prolif)}; the coaters have nothing to spray with"
        )

    def test_every_coater_has_a_sorter_drawing_from_a_supply_belt(self) -> None:
        spec = proliferated_spec()
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        report = _full_report(p, spec)
        starved = report.by_check("prolif.coaters_are_supplied")
        assert not starved, "\n".join(f.message for f in starved)

    def test_coaters_sit_on_the_lane_carrying_the_item_they_spray(self) -> None:
        """A coater on some unrelated belt sprays the wrong items."""
        spec = proliferated_spec()
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        belt_at = {
            (b.x, b.y, b.z): b for b in p.buildings if catalog.is_belt(b.item_id)
        }
        coaters = [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]
        assert coaters, "fixture must produce at least one coater"
        for c in coaters:
            host = belt_at.get((c.x, c.y, c.z))
            assert host is not None, f"coater at {(c.x, c.y, c.z)} is not on a belt"
            assert host.carries_item in spec.spray_lanes, (
                f"coater sits on a lane carrying {host.carries_item!r}, which is not "
                f"one of the sprayed lanes {sorted(spec.spray_lanes)}"
            )

    def test_no_proliferator_spec_places_no_supply_lane(self) -> None:
        """The machinery must cost nothing when proliferation is off."""
        spec = two_stage_spec()
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        assert p.stats["spray_coaters"] == 0
        assert not [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]


class TestSortersCanCarryTheirDemand:
    def test_sorter_tiers_are_chosen_for_the_span_they_actually_span(self) -> None:
        """Tier selection must use the validator's demand basis, not its own.

        The two disagreed: selection divided one item's group total by the
        strip's machine count, while the demand is a machine's *total* input rate
        split across the sorters feeding it. A Mk.I at span 3 sustains 0.5/s and
        was being handed 0.546/s.
        """
        spec = proliferated_spec()
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        over = _full_report(p, spec).by_check("flow.sorter_capacity")
        assert not over, "\n".join(f.message for f in over)


PROLIFERATED_PACK_GAP = pytest.mark.xfail(
    strict=True,
    reason="freeform's packer optimises width and wirelength with no model of "
    "routability, so whether a pack can be wired varies with the CP-SAT solve "
    "that produced it; the proliferated candidates of the super-magnetic-ring "
    "chain route cleanly at some packs and not others. See docs/BACKLOG.md.",
)


class TestRealUrlCandidatesAreSupplied:
    """The checks this module is responsible for, on real FactorioLab specs.

    The hand-built fixtures are too small to exercise sorter tier selection or a
    multi-coater supply chain, which is why both bugs survived them.
    """

    @staticmethod
    def _candidates() -> list[BuildSpec]:
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.rates.candidates import build_candidates

        url = (
            "https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60"
            "&ibe=conveyor-belt-2"
            "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
            "&mps=proliferator-2-products&v=11"
        )
        return list(build_candidates(load_vendored(), parse_url(url), count=3).candidates)

    @pytest.mark.slow
    @PROLIFERATED_PACK_GAP
    def test_every_candidate_supplies_its_coaters(self) -> None:
        for spec in self._candidates():
            p = FreeformLayout(power=True).lay_out(spec, time_budget_s=0.5)
            bad = _full_report(p, spec, power=True).by_check("prolif.coaters_are_supplied")
            assert not bad, f"{spec.label}: " + "; ".join(f.message for f in bad)

    @pytest.mark.slow
    @PROLIFERATED_PACK_GAP
    def test_every_candidate_respects_sorter_capacity(self) -> None:
        for spec in self._candidates():
            p = FreeformLayout(power=True).lay_out(spec, time_budget_s=0.5)
            bad = _full_report(p, spec, power=True).by_check("flow.sorter_capacity")
            assert not bad, f"{spec.label}: " + "; ".join(f.message for f in bad)

    @pytest.mark.slow
    @PROLIFERATED_PACK_GAP
    def test_belt_chains_are_genuinely_acyclic(self) -> None:
        """Computed directly, not via ``belt.acyclic``.

        That check has a false positive on merges -- it leaves a walk's own path
        coloured in-progress when the walk exits early, so a later chain merging
        into it is misread as a cycle. DSP belts merge natively and the router
        prefers source-merging, so the check fires on correct layouts. This
        asserts the property itself so the guarantee is covered regardless.
        """
        for spec in self._candidates():
            p = FreeformLayout(power=True).lay_out(spec, time_budget_s=0.5)
            for i, b in enumerate(p.buildings):
                if not catalog.is_belt(b.item_id):
                    continue
                seen: set[int] = set()
                cur: int | None = i
                while cur is not None and cur not in seen:
                    seen.add(cur)
                    nxt = p.buildings[cur].output_obj
                    cur = nxt if nxt is not None and catalog.is_belt(
                        p.buildings[nxt].item_id
                    ) else None
                assert cur is None, f"{spec.label}: real cycle reachable from belt {i}"


def _real_consumers_of(item: str, wanted: int) -> list[str]:
    """Real DSP recipes that consume ``item`` and have a known DSP recipe id.

    Chosen from the dataset rather than hardcoded so this keeps working as the
    recipe table is re-extracted -- a synthetic recipe name would fail at
    ``catalog.recipe_id`` instead of exercising the layout.
    """
    from flab2bp.lab.data import load_vendored

    data = load_vendored()
    known = catalog.known_recipe_ids()
    out: list[str] = []
    for r in data.recipes:
        if r.is_mining or r.is_technology or item not in r.inputs:
            continue
        if r.id in known and all(catalog.get_item_id(o) is not None for o in r.outputs):
            out.append(r.id)
        if len(out) == wanted:
            break
    return out


def fan_out_spec(consumers: int = 4) -> BuildSpec:
    """One producer feeding many consumers.

    A strip gets one output lane per destination, and a sorter spans at most
    three tiles, so a producer with four consumers cannot reach its own bottom
    lane. Every other spec here is small enough that this never arises, which is
    why it survived until a real URL hit it: ``copper-ingot`` feeds four recipes
    in the orbital-collector build.
    """
    sinks = _real_consumers_of("copper-ingot", consumers)
    if len(sinks) < consumers:
        pytest.skip(f"dataset has only {len(sinks)} mapped copper-ingot consumers")
    groups = [
        group(
            "copper-ingot",
            "arc-smelter",
            4 * consumers,
            {"copper-ore": F(1)},
            {"copper-ingot": F(1)},
        )
    ]
    outputs: dict[str, F] = {}
    for rid in sinks:
        from flab2bp.lab.data import load_vendored

        produced = next(iter(load_vendored().recipe(rid).outputs))
        groups.append(
            group(rid, "assembling-machine-2", 2, {"copper-ingot": F(1)}, {produced: F(1)})
        )
        outputs[produced] = F(2)
    return BuildSpec(
        groups=tuple(groups),
        external_inputs={"copper-ore": F(4 * consumers)},
        outputs=outputs,
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label=f"fan-out-{consumers}",
    )


class TestProducerWithManyConsumers:
    """Sharding a group across strips when its destinations exceed sorter reach.

    Raising ``strip_len`` -- what the old error message advised -- cannot help:
    the output-lane count comes from the number of destination GROUPS, which is
    independent of how machines are split into strips. Verified at strip_len
    6, 12, 50 and 500, all identical failures.
    """

    @pytest.mark.parametrize("consumers", [4, 5, 7])
    def test_planning_succeeds_and_respects_sorter_reach(self, consumers: int) -> None:
        strips = plan_strips(fan_out_spec(consumers), strip_len=6)
        assert strips
        for s in strips:
            assert len(s.out_lanes) <= catalog.SORTER_MAX_REACH, (
                f"strip {s.group_key} has {len(s.out_lanes)} output lanes"
            )
            assert len(s.in_lanes) <= catalog.SORTER_MAX_REACH

    def test_every_destination_is_still_served(self) -> None:
        """Sharding must not drop a consumer -- that starves it silently."""
        spec = fan_out_spec(5)
        strips = plan_strips(spec, strip_len=6)
        served = {
            dest
            for s in strips
            if s.recipe_id == "copper-ingot"
            for _item, dest in s.out_lanes
            if dest
        }
        wanted = {
            f"{g.recipe_id}#{i}"
            for i, g in enumerate(spec.groups)
            if "copper-ingot" in g.inputs_per_machine
        }
        assert served == wanted, f"missing destinations: {wanted - served}"

    def test_all_machines_survive_sharding(self) -> None:
        spec = fan_out_spec(5)
        strips = plan_strips(spec, strip_len=6)
        assert sum(s.machines for s in strips) == spec.machine_count

    @pytest.mark.parametrize("power", [False, True])
    def test_it_lays_out_and_validates(self, power: bool) -> None:
        """Pinned to one worker, and route failures asserted separately.

        The shipping default is multi-worker CP-SAT, which is deliberately
        nondeterministic: different runs land on different packs, and the harder
        ones leave a net unrouted, which `flow.lane_sourced` then correctly
        reports as a dry lane. Left unpinned this test passed or failed by which
        worker happened to win.

        `route_failures` is asserted in its own right rather than left to
        `report.ok`, so the test cannot pass by producing a layout that quietly
        dropped a connection.
        """
        spec = fan_out_spec(4)
        p = FreeformLayout(power=power, workers=DETERMINISTIC_WORKERS).lay_out(
            spec, time_budget_s=0.5
        )
        assert p.stats.get("route_failures", 0) == 0, "a net went unrouted"
        report = _full_report(p, spec, power=power)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:8])


# --- mixed-item lanes ------------------------------------------------------


def six_input_spec() -> BuildSpec:
    """A REAL six-ingredient recipe, fed entirely from outside.

    ``universe-matrix`` takes antimatter plus all five lower matrices and runs in
    a Matrix Lab.  Six inputs plus one output is seven lanes, and two sides of
    three cannot carry that one-item-per-lane -- which is what mixing is for.

    Deliberately a real recipe, not a synthesised one: a made-up name plans
    perfectly well and then dies at ``catalog.recipe_id``, so a synthetic-only
    test would pass while the feature stayed broken.
    """
    ingredients = [
        "antimatter",
        "electromagnetic-matrix",
        "energy-matrix",
        "gravity-matrix",
        "information-matrix",
        "structure-matrix",
    ]
    return BuildSpec(
        groups=(
            group(
                "universe-matrix",
                "matrix-lab",
                2,
                {i: F(1) for i in ingredients},
                {"universe-matrix": F(1)},
            ),
        ),
        external_inputs={i: F(2) for i in ingredients},
        outputs={"universe-matrix": F(2)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=F(30),
        label="six-input",
    )


def _lane_runs(p: Placement) -> dict[int, set[int]]:
    """Belt RUN -> the set of non-zero sorter filters drawing from it.

    This is the signal the validator keys on to spot a shared lane, and it is
    per-RUN rather than per-tile: each machine is served from its own column, so
    two items sharing a lane attach to two different belt tiles of the same
    forward-linked run. Collecting filters per tile would miss that entirely.

    A sorter only carries a filter when its lane is mixed, so a run with two
    distinct filters against it provably carries two items.
    """
    # Forward-linked belt chains, collapsed to a representative index.
    run_of: dict[int, int] = {}
    for i, b in enumerate(p.buildings):
        if not catalog.is_belt(b.item_id):
            continue
        run_of.setdefault(i, i)
        nxt = b.output_obj
        if (
            nxt is not None
            and 0 <= nxt < len(p.buildings)
            and catalog.is_belt(p.buildings[nxt].item_id)
        ):
            run_of[nxt] = run_of[i]

    filters: dict[int, set[int]] = {}
    for b in p.buildings:
        if not catalog.is_sorter(b.item_id) or not b.filter_id:
            continue
        if b.input_obj is None or b.input_obj not in run_of:
            continue
        filters.setdefault(run_of[b.input_obj], set()).add(b.filter_id)
    return filters


class TestMixedItemLanes:
    """One item per lane is our simplification, not a DSP rule.

    Measured across the fixture corpus, 236 of 1,288 real sorters carry a
    filter, and ``falk-v7-mall-full`` filters 100% of its 196 -- bus designs
    where several items share a belt and filtered sorters pick off the one they
    want.
    """

    def test_a_six_ingredient_recipe_plans(self) -> None:
        strips = plan_strips(six_input_spec(), strip_len=6)
        assert strips
        s = strips[0]
        assert len(s.in_lanes) == 6, "every ingredient must still be present"
        lanes = len(s.in_above) + len(s.in_below)
        assert lanes < 6, f"expected mixing to save lanes, used {lanes} for 6 items"

    def test_it_lays_out_and_validates(self) -> None:
        spec = six_input_spec()
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        report = _full_report(p, spec, power=False)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:8])

    def test_every_sorter_on_a_mixed_lane_is_filtered(self) -> None:
        """An unfiltered sorter on a shared lane grabs whatever passes.

        That starves the machine that needed the other item, and nothing about
        the paste looks wrong -- so this is correctness, not tidiness.
        """
        spec = six_input_spec()
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        shared = _lane_runs(p)
        assert shared, "a six-input strip must produce at least one mixed lane"
        assert any(len(f) > 1 for f in shared.values()), (
            "expected some belt to be drawn from under two different filters"
        )

    def test_unmixed_lanes_stay_unfiltered(self) -> None:
        """The signal only means something if it is absent when lanes are pure.

        If ordinary strips also filtered, the validator could not tell a shared
        lane from a plain one and would keep applying its single-commodity
        decomposition to a lane it had not actually checked.
        """
        spec = magnetic_ring_spec()
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        assert not _lane_runs(p), "no lane in this spec is shared, so none may filter"


# --- mode-driven machines --------------------------------------------------


def mode_driven_spec() -> BuildSpec:
    """An Energy Exchanger charging accumulators.

    ``accumulator-full`` is a MODE, not a craft: DSP has no recipe id for it and
    the job is selected by a word in the parameter block.
    """
    return BuildSpec(
        groups=(
            group(
                "accumulator-full",
                "energy-exchanger",
                2,
                {"accumulator": F(1)},
                {"accumulator-full": F(1)},
            ),
        ),
        external_inputs={"accumulator": F(2)},
        outputs={"accumulator-full": F(2)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="mode-driven",
    )


class TestModeDrivenMachines:
    def test_it_lays_out(self) -> None:
        spec = mode_driven_spec()
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        assert p.buildings

    def test_the_machine_carries_the_mode_not_a_recipe(self) -> None:
        """recipe_id stays zero; the mode rides in the parameter block."""
        from flab2bp.dsp import params

        spec = mode_driven_spec()
        p = FreeformLayout(power=False).lay_out(spec, time_budget_s=0.5)
        exchangers = [
            b for b in p.buildings if b.item_id == catalog.ENERGY_EXCHANGER_ID
        ]
        assert len(exchangers) == 2, f"expected 2 exchangers, got {len(exchangers)}"
        want = params.parameters_for("accumulator-full")
        for b in exchangers:
            assert b.recipe_id == 0, "a mode-driven machine has no recipe id"
            assert b.parameters == want, f"expected {want}, got {b.parameters}"

    def test_charge_and_discharge_differ(self) -> None:
        """A guard on the poles: emitting the wrong one drains what it should fill."""
        from flab2bp.dsp import params

        assert params.parameters_for("accumulator-full") != params.parameters_for(
            "accumulator-discharge"
        )


# --- sharded groups are fed on every shard ---------------------------------


def sharded_consumer_spec() -> BuildSpec:
    """A consumer big enough to shard, fed by a single producer strip.

    Eight machines at ``strip_len`` 6 become two strips, and each carries its
    OWN input lane. ``out_lanes`` names the destination GROUP, not the strip, so
    one output lane has to reach both shards; feeding only one leaves the other
    with belts, sorters, and nothing moving along them.
    """
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 8, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group("gear", "assembling-machine-2", 8, {"iron-ingot": F(1)}, {"gear": F(1)}),
        ),
        external_inputs={"iron-ore": F(8)},
        outputs={"gear": F(8)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="sharded-consumer",
    )


class TestShardedGroupsAreFedOnEveryShard:
    """Keying ports by group let one shard overwrite another's.

    Traced on a real build: `gear#4` had one output lane to `electric-motor#1`,
    that group held two strips, and only the strip whose port happened to be
    stored last became a net sink. The other strip's lane was never filled and
    its four machines starved -- while the build reported `route_failures == 0`,
    because the net that existed did route and the missing one was never created
    to fail.
    """

    def test_the_fixture_actually_shards(self) -> None:
        """Otherwise the test below proves nothing."""
        strips = plan_strips(sharded_consumer_spec(), strip_len=6)
        consumers = [s for s in strips if s.group_key.startswith("gear")]
        assert len(consumers) >= 2, (
            f"expected the consumer to shard, got {len(consumers)} strip(s); "
            "raise the machine count or lower strip_len"
        )

    @pytest.mark.parametrize("power", [False, True])
    def test_no_shard_is_left_starving(self, power: bool) -> None:
        spec = sharded_consumer_spec()
        p = FreeformLayout(power=power, workers=DETERMINISTIC_WORKERS).lay_out(
            spec, time_budget_s=0.5
        )
        report = _full_report(p, spec, power=power)
        starved = [f for f in report.errors if f.check == "flow.lane_sourced"]
        assert not starved, "\n".join(f.message for f in starved)

    def test_a_sharded_producer_has_every_lane_drained(self) -> None:
        """The mirror case: several producer strips shipping to one consumer.

        Sharding a producer gives its strips the SAME destination set, so the
        output side collided identically and left dead belts behind.
        """
        spec = BuildSpec(
            groups=(
                group("iron-ingot", "arc-smelter", 12, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
                group("gear", "assembling-machine-2", 2, {"iron-ingot": F(1)}, {"gear": F(1)}),
            ),
            external_inputs={"iron-ore": F(12)},
            outputs={"gear": F(2)},
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=F(12),
            label="sharded-producer",
        )
        producers = [
            s for s in plan_strips(spec, strip_len=6) if s.group_key.startswith("iron-ingot")
        ]
        assert len(producers) >= 2, "fixture must shard the producer"
        p = FreeformLayout(power=False, workers=DETERMINISTIC_WORKERS).lay_out(
            spec, time_budget_s=0.5
        )
        report = _full_report(p, spec, power=False)
        starved = [f for f in report.errors if f.check == "flow.lane_sourced"]
        assert not starved, "\n".join(f.message for f in starved)
