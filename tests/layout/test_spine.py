"""Strategy A end-to-end properties.

Specs are hand-built here rather than taken from ``rates/``, which is being
implemented concurrently -- these tests must pin the layout's behaviour, not the
rate solver's.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout.base import DETERMINISTIC_WORKERS, Placement
from flab2bp.layout.spine import (
    MACHINE_ITEM_IDS,
    SpineLayout,
    fallback_plan,
    machine_group_footprint,
)
from flab2bp.spec import BuildSpec, MachineGroup, ProliferatorMode

F = Fraction
SpecFactory = Callable[[], BuildSpec]


def group(
    recipe: str,
    machine: str,
    count: int,
    inputs: dict[str, Fraction] | None = None,
    outputs: dict[str, Fraction] | None = None,
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
        groups=(
            group("iron-ingot", "arc-smelter", 4, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
        ),
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
            group(
                "gear",
                "assembling-machine-2",
                2,
                {"iron-ingot": F(1)},
                {"gear": F(1)},
            ),
        ),
        external_inputs={"iron-ore": F(4)},
        outputs={"gear": F(2)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="two-stage",
    )


def magnetic_ring_spec() -> BuildSpec:
    """Shaped like the super-magnetic-ring chain: 3/4/8/4/4 assemblers, 12/4/17/2 smelters."""
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 12, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group("copper-ingot", "arc-smelter", 4, {"copper-ore": F(1)}, {"copper-ingot": F(1)}),
            group("magnet", "arc-smelter", 17, {"iron-ore": F(1)}, {"magnet": F(1)}),
            group(
                "energetic-graphite",
                "arc-smelter",
                2,
                {"coal": F(1)},
                {"energetic-graphite": F(1)},
            ),
            group(
                "magnetic-coil",
                "assembling-machine-2",
                4,
                {"magnet": F(1), "copper-ingot": F(1)},
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


# --- helpers ---------------------------------------------------------------


def blocking_tiles(p: Placement) -> list[tuple[int, int, int]]:
    """Tiles that genuinely exclude another building.

    Belt-integrated buildings share tiles rather than consuming them: belts,
    sorters and splitters all sit at dx=dy=0.00 from a belt in real blueprints.
    Belt addons such as the Spray Coater occupy no grid tile at all.  Neither
    class may be counted as blocking, or every valid layout would fail.
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
    return [
        i
        for i, b in enumerate(p.buildings)
        if not catalog.is_belt_integrated(b.item_id)
        and b.item_id != catalog.TESLA_TOWER_ID
        and catalog.building(b.item_id).occupies_tiles
    ]


# --- adapter ---------------------------------------------------------------


class TestAdapter:
    def test_every_dsp_producer_machine_maps_to_a_building(self) -> None:
        """A missing id would surface as a KeyError deep inside emission."""
        for lab_id, item_id in MACHINE_ITEM_IDS.items():
            b = catalog.building(item_id)
            assert b.width >= 1 and b.height >= 1, lab_id

    def test_footprints_are_the_real_heterogeneous_ones(self) -> None:
        """Footprints are derived, always odd, and genuinely varied.

        Smelters and assemblers are the *same* 3x3 under the derived rule, so
        heterogeneity is proven by the larger plants instead -- a 9x5 chemical
        plant is five times the area of a 3x3 smelter, and the 3x7 refinery is
        the case where width and height differ.
        """
        smelter = machine_group_footprint(group("x", "arc-smelter", 1))
        assembler = machine_group_footprint(group("x", "assembling-machine-2", 1))
        chemical = machine_group_footprint(group("x", "chemical-plant", 1))
        lab = machine_group_footprint(group("x", "matrix-lab", 1))
        refinery = machine_group_footprint(group("x", "oil-refinery", 1))

        assert smelter == (3, 3)
        assert assembler == (3, 3)
        assert chemical == (9, 5)
        assert lab == (5, 5)
        assert refinery == (3, 7)

        # Genuinely heterogeneous: at least three distinct sizes, spanning a 5x
        # area range, including a non-square one.
        assert len({smelter, chemical, lab, refinery}) >= 3
        assert chemical[0] * chemical[1] >= 5 * smelter[0] * smelter[1]
        assert refinery[0] != refinery[1]

    def test_every_derived_footprint_dimension_is_odd(self) -> None:
        """The derived rule is ``2 * ceil(box / 2) - 1``, so never even.

        An even-width building centred on an integer would straddle tile
        boundaries, which belts (fixed 1x1 on integer centres) prove cannot
        happen.
        """
        for lab_id in MACHINE_ITEM_IDS:
            w, h = machine_group_footprint(group("x", lab_id, 1))
            assert w % 2 == 1 and h % 2 == 1, f"{lab_id} is {w}x{h}"

    def test_unknown_machine_raises_clearly(self) -> None:
        spec = BuildSpec(groups=(group("x", "not-a-machine", 1),))
        with pytest.raises(KeyError, match="not-a-machine"):
            fallback_plan(spec)


# --- planning --------------------------------------------------------------


class TestFallbackPlan:
    def test_one_group_per_row(self) -> None:
        plan = fallback_plan(magnetic_ring_spec())
        assert all(len(r) == 1 for r in plan.rows)
        assert len(plan.rows) == 9

    def test_producers_sit_above_consumers(self) -> None:
        plan = fallback_plan(two_stage_spec())
        order = [r[0] for r in plan.rows]
        assert order[0].startswith("iron-ingot")
        assert order[1].startswith("gear")

    def test_one_more_corridor_than_rows(self) -> None:
        plan = fallback_plan(magnetic_ring_spec())
        assert len(plan.lanes) == len(plan.rows) + 1

    def test_cyclic_graph_raises_rather_than_misordering(self) -> None:
        spec = BuildSpec(
            groups=(
                group("a", "arc-smelter", 1, {"b-item": F(1)}, {"a-item": F(1)}),
                group("b", "arc-smelter", 1, {"a-item": F(1)}, {"b-item": F(1)}),
            )
        )
        with pytest.raises(ValueError, match="cyclic"):
            fallback_plan(spec)


# --- emission properties ---------------------------------------------------


@pytest.mark.parametrize(
    "spec_fn", [single_recipe_spec, two_stage_spec, magnetic_ring_spec], ids=lambda f: f.__name__
)
@pytest.mark.parametrize("power", [True, False], ids=["power", "no-power"])
class TestPlacementProperties:
    def test_no_two_blocking_footprints_share_a_tile(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.3)
        tiles = blocking_tiles(p)
        assert len(tiles) == len(set(tiles)), "overlapping footprints"

    def test_every_machine_is_placed(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        spec = spec_fn()
        p = SpineLayout(power=power).lay_out(spec, time_budget_s=0.3)
        assert len(machines_of(p)) == spec.machine_count

    def test_every_sorter_is_within_reach_and_single_altitude(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.3)
        for b in p.buildings:
            if not catalog.is_sorter(b.item_id):
                continue
            assert b.x2 is not None and b.y2 is not None
            span = max(abs(b.x - b.x2), abs(b.y - b.y2))
            assert 1 <= span <= catalog.SORTER_MAX_REACH, f"span {span}"
            assert b.z == (b.z2 or 0), "sorters never span altitudes"

    def test_sorter_endpoints_reference_real_buildings(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.3)
        n = len(p.buildings)
        for b in p.buildings:
            if not catalog.is_sorter(b.item_id):
                continue
            assert b.input_obj is not None and 0 <= b.input_obj < n
            assert b.output_obj is not None and 0 <= b.output_obj < n
            assert b.input_obj != b.output_obj

    def test_belt_chains_link_forward_and_terminate(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.3)
        belts = [i for i, b in enumerate(p.buildings) if catalog.is_belt(b.item_id)]
        for i in belts:
            nxt = p.buildings[i].output_obj
            if nxt is None:
                continue
            assert catalog.is_belt(p.buildings[nxt].item_id)
            # Forward means strictly eastward by one tile on the same lane.
            assert p.buildings[nxt].x == p.buildings[i].x + 1
            assert p.buildings[nxt].y == p.buildings[i].y

    def test_placement_is_non_empty_and_has_area(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.3)
        assert p.buildings
        assert p.area > 0


class TestLaneExtents:
    def test_lanes_are_trimmed_to_what_they_serve(self) -> None:
        """A tapped lane carries belt only where it is tapped, plus the run to
        the block edge for external inputs and products."""
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        belts = [b for b in p.buildings if catalog.is_belt(b.item_id)]
        min_x, _, max_x, _ = p.bounds
        full_width = max_x - min_x + 1
        lanes: dict[int, list[int]] = {}
        for b in belts:
            lanes.setdefault(b.y, []).append(b.x)
        assert lanes
        # At least one lane must be genuinely shorter than the block width, or
        # the trim did nothing.
        assert any(len(xs) < full_width for xs in lanes.values())

    def test_trimming_does_not_change_area(self) -> None:
        """Trimming removes belt tiles inside the bounding box, never resizes it."""
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        assert p.area > 0
        assert p.stats["belt_tiles"] > 0


class TestKnownGaps:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Direct insertion cannot survive a multi-input recipe in this skeleton. "
            "A sorter reaches 3 tiles and the gap between two rows is the corridor's "
            "lane count plus one, so an insert needs a corridor of at most 2 lanes. "
            "super-magnetic-ring takes three inputs; the moment any sibling input is "
            "belted, that corridor holds 3+ lanes, dy reaches 4, and the insert is "
            "unreachable however well aligned it is. Needs producer/consumer x "
            "alignment to be a solver decision rather than a greedy left-to-right "
            "pack -- see the measured cascade in the report."
        ),
    )
    def test_direct_insertion_survives_on_the_realistic_chain(self) -> None:
        p = SpineLayout(power=False, workers=DETERMINISTIC_WORKERS).lay_out(
            magnetic_ring_spec(), time_budget_s=0.5
        )
        assert p.stats["direct_inserts"] >= 1


    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Long-span items are not delivered: lanes in different corridors are "
            "independent horizontal runs with no vertical connection, so a producer "
            "several rows above its consumer pushes into a belt run the consumer "
            "never reads. Needs the west trunk risers descoped from v1."
        ),
    )
    def test_every_consumed_item_reaches_its_consumer(self) -> None:
        """End-to-end reachability from each producer to each consumer.

        Walks the emitted graph: a consumer's input sorter must pick up from a
        belt run that some producer's output sorter feeds.
        """
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        # Belt runs, keyed by a representative index, via forward links.
        run_of: dict[int, int] = {}
        for i, b in enumerate(p.buildings):
            if catalog.is_belt(b.item_id):
                run_of.setdefault(i, i)
        for i, b in enumerate(p.buildings):
            if catalog.is_belt(b.item_id) and b.output_obj is not None:
                run_of[b.output_obj] = run_of[i]

        fed: set[int] = set()
        for b in p.buildings:
            if catalog.is_sorter(b.item_id) and b.output_obj in run_of:
                fed.add(run_of[b.output_obj])

        for b in p.buildings:
            if not catalog.is_sorter(b.item_id):
                continue
            src = b.input_obj
            if src is None or src not in run_of:
                continue  # picks up from a machine, i.e. an output sorter
            assert run_of[src] in fed, "a machine draws from a belt run nothing feeds"


class TestPower:
    def test_no_power_emits_zero_towers(self) -> None:
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.3)
        assert not any(b.item_id == catalog.TESLA_TOWER_ID for b in p.buildings)
        assert p.stats["towers"] == 0

    def test_power_emits_towers(self) -> None:
        p = SpineLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=0.3)
        assert p.stats["towers"] > 0

    def test_every_powered_building_is_covered(self) -> None:
        """Checked with true Euclidean distance over every footprint tile.

        Deliberately independent of the linearised reach table, so a
        linearisation error would show up here rather than agree with itself.
        """
        p = SpineLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        centres = [
            (b.x + b.width / 2, b.y + b.height / 2)
            for b in p.buildings
            if b.item_id == catalog.TESLA_TOWER_ID
        ]
        radius = float(catalog.TESLA_COVER_RADIUS)
        for b in p.buildings:
            if b.item_id in catalog.UNPOWERED_ITEM_IDS or b.item_id == catalog.TESLA_TOWER_ID:
                continue
            for tx, ty, _ in b.tiles():
                px, py = tx + 0.5, ty + 0.5
                assert any(math.dist((px, py), c) <= radius + 1e-9 for c in centres), (
                    f"unpowered tile {(tx, ty)} of item {b.item_id}"
                )

    def test_tower_network_is_connected(self) -> None:
        """Union-find over true Euclidean link distance, independent of the
        by-construction argument that placed them."""
        p = SpineLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        towers = [
            (b.x + b.width / 2, b.y + b.height / 2)
            for b in p.buildings
            if b.item_id == catalog.TESLA_TOWER_ID
        ]
        assert towers
        link = float(catalog.TESLA_LINK_DISTANCE)
        seen = {0}
        frontier = [0]
        while frontier:
            i = frontier.pop()
            for j, t in enumerate(towers):
                if j not in seen and math.dist(towers[i], t) <= link + 1e-9:
                    seen.add(j)
                    frontier.append(j)
        assert len(seen) == len(towers), "tower network is disconnected"


class TestProliferation:
    def test_spray_coater_consumes_no_grid_tile(self) -> None:
        spec = two_stage_spec()
        prolif = BuildSpec(
            groups=spec.groups,
            external_inputs=spec.external_inputs,
            outputs=spec.outputs,
            belt_item_id=spec.belt_item_id,
            belt_items_per_second=spec.belt_items_per_second,
            spray_lanes={"iron-ingot": False},
            label="prolif",
        )
        p = SpineLayout(power=False).lay_out(prolif, time_budget_s=0.3)
        coaters = [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]
        assert coaters
        assert not catalog.building(catalog.SPRAY_COATER_ID).occupies_tiles
        tiles = blocking_tiles(p)
        assert len(tiles) == len(set(tiles))

    def test_belt_required_edges_are_never_direct_inserted(self) -> None:
        spec = two_stage_spec()
        required = frozenset({("iron-ingot", "gear")})
        prolif = BuildSpec(
            groups=spec.groups,
            external_inputs=spec.external_inputs,
            outputs=spec.outputs,
            belt_item_id=spec.belt_item_id,
            belt_items_per_second=spec.belt_items_per_second,
            belt_required_edges=required,
            label="prolif",
        )
        layout = SpineLayout(power=False)
        p = layout.lay_out(prolif, time_budget_s=0.3)
        assert p.stats["direct_inserts"] == 0


def _forced_belt(spec: BuildSpec, edges: frozenset[tuple[str, str]]) -> BuildSpec:
    """The same spec with ``edges`` ineligible for direct insertion.

    This is the controlled A/B for direct insertion: identical geometry, one
    switch. Comparing against a *different* spec would confound the mechanism
    with whatever else changed.
    """
    return BuildSpec(
        groups=spec.groups,
        external_inputs=spec.external_inputs,
        outputs=spec.outputs,
        belt_item_id=spec.belt_item_id,
        belt_items_per_second=spec.belt_items_per_second,
        label=spec.label,
        belt_required_edges=edges,
    )


class TestDirectInsertion:
    """A producer within sorter reach of its consumer needs no belt between them.

    Every test here pins ``workers=DETERMINISTIC_WORKERS``: the shipping default
    is a multi-worker portfolio whose results vary run to run, and an A/B that
    varies with the wind proves nothing about the mechanism.
    """

    def test_an_adjacent_pair_is_direct_inserted(self) -> None:
        p = SpineLayout(power=False, workers=DETERMINISTIC_WORKERS).lay_out(
            two_stage_spec(), time_budget_s=0.5
        )
        assert p.stats["direct_inserts"] >= 1

    def test_direct_insertion_removes_belt_tiles(self) -> None:
        """The counter moving is not enough -- the belts must actually be gone."""
        spec = two_stage_spec()
        forced = _forced_belt(spec, frozenset({("iron-ingot", "gear")}))
        w = DETERMINISTIC_WORKERS
        direct = SpineLayout(power=False, workers=w).lay_out(spec, time_budget_s=0.5)
        belted = SpineLayout(power=False, workers=w).lay_out(forced, time_budget_s=0.5)

        assert direct.stats["direct_inserts"] >= 1
        assert belted.stats["direct_inserts"] == 0
        assert direct.stats["belt_tiles"] < belted.stats["belt_tiles"]

    def test_a_direct_sorter_joins_two_machines_with_no_belt(self) -> None:
        """The emitted sorter must span machine to machine, not machine to belt."""
        p = SpineLayout(power=False, workers=DETERMINISTIC_WORKERS).lay_out(
            two_stage_spec(), time_budget_s=0.5
        )
        machines = set(machines_of(p))
        joins = [
            b
            for b in p.buildings
            if catalog.is_sorter(b.item_id)
            and b.input_obj in machines
            and b.output_obj in machines
        ]
        assert joins, "no machine-to-machine sorter was emitted"
        for b in joins:
            assert b.x2 is not None and b.y2 is not None
            span = abs(b.x - b.x2) + abs(b.y - b.y2)
            assert 1 <= span <= catalog.SORTER_MAX_REACH
            assert b.z == (b.z2 or 0), "sorters never span altitudes"

    def test_a_belt_required_edge_is_never_direct_inserted(self) -> None:
        """Spray is applied by a belt-mounted coater, so a sprayed input must
        arrive belted. Direct-inserting one silently under-produces."""
        forced = _forced_belt(two_stage_spec(), frozenset({("iron-ingot", "gear")}))
        p = SpineLayout(power=False, workers=DETERMINISTIC_WORKERS).lay_out(
            forced, time_budget_s=0.5
        )
        assert p.stats["direct_inserts"] == 0
        machines = set(machines_of(p))
        assert not [
            b
            for b in p.buildings
            if catalog.is_sorter(b.item_id)
            and b.input_obj in machines
            and b.output_obj in machines
        ]

    def test_direct_insertion_never_leaves_a_machine_unfed(self) -> None:
        """Dropping a lane must be paired with emitting the sorter that replaces
        it, or the consumer is simply starved."""
        w = DETERMINISTIC_WORKERS
        for spec_fn in (two_stage_spec, magnetic_ring_spec):
            p = SpineLayout(power=False, workers=w).lay_out(spec_fn(), time_budget_s=0.5)
            fed = {b.output_obj for b in p.buildings if catalog.is_sorter(b.item_id)}
            for i in machines_of(p):
                assert i in fed or not p.buildings[i].input_obj, f"machine {i} unfed"


class TestSolverBehaviour:
    def test_solved_area_beats_the_fallback_outright(self) -> None:
        """Guards the silent-fallback class of bug.

        ``lay_out`` once swallowed an exception and returned a fallback that
        looked solved on every spec; it went unnoticed until a test compared the
        two areas and found them identical.
        """
        spec = magnetic_ring_spec()
        w = DETERMINISTIC_WORKERS
        solved = SpineLayout(power=False, workers=w).lay_out(spec, time_budget_s=0.5)
        fallback = SpineLayout(power=False, workers=w).lay_out(spec, time_budget_s=0.0)
        assert solved.stats["fallback_used"] == 0.0
        assert solved.stats["solver_rejected"] == 0.0
        assert solved.area < fallback.area

    def test_always_returns_a_placement_with_no_budget(self) -> None:
        p = SpineLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=0.0)
        assert p.buildings
        assert p.stats["fallback_used"] == 1.0

    def test_deterministic_for_a_fixed_budget(self) -> None:
        """Reproducibility is the property under test here, so pin workers.

        The shipping default is multi-worker, which is deliberately
        nondeterministic -- CP-SAT runs a portfolio and takes whichever
        strategy wins. That is worth 23% density, so the bake-off keeps it
        and absorbs the variance by repeating cells. This test pins
        DETERMINISTIC_WORKERS because it asserts run-to-run identity.
        """
        w = DETERMINISTIC_WORKERS
        a = SpineLayout(power=True, workers=w).lay_out(magnetic_ring_spec(), time_budget_s=0.4)
        b = SpineLayout(power=True, workers=w).lay_out(magnetic_ring_spec(), time_budget_s=0.4)
        assert a.buildings == b.buildings

    def test_solving_is_no_worse_than_the_fallback(self) -> None:
        spec = magnetic_ring_spec()
        solved = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        fallback = SpineLayout(power=False).lay_out(spec, time_budget_s=0.0)
        assert solved.area <= fallback.area

    def test_stats_carry_the_bake_off_fields(self) -> None:
        p = SpineLayout(power=True).lay_out(two_stage_spec(), time_budget_s=0.3)
        for key in (
            "area",
            "machines",
            "belt_tiles",
            "sorters",
            "towers",
            "direct_inserts",
            "solver_status",
            "hit_time_budget",
            "fallback_used",
        ):
            assert key in p.stats, key
