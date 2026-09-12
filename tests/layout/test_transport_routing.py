"""Physical edge cases for constructive transport routing."""

from __future__ import annotations

import math
from fractions import Fraction
from itertools import combinations
from time import monotonic

from pysat.solvers import Cadical195

from flab2bp.dsp import catalog, colliders
from flab2bp.layout import finalize, junction, validate
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import Placement
from flab2bp.layout.markers import self_loop_prime_heads
from flab2bp.layout.routing_domain import spherical_overflight_limit
from flab2bp.layout.slots import assign_sorter_slots
from flab2bp.layout.transport_routing import paths, solver
from flab2bp.layout.transport_routing.allocation import select_topology
from flab2bp.layout.transport_routing.budget import WorkBudget
from flab2bp.layout.transport_routing.cnf import FactorCNF
from flab2bp.layout.transport_routing.construction import Terminal, path_through
from flab2bp.layout.transport_routing.flights import Flight, occupied_cells
from flab2bp.layout.transport_routing.inventory import prepare_inventory
from flab2bp.layout.transport_routing.routing import RoutingRun, TemplateConstructor
from flab2bp.layout.transport_routing.runtime import TransportRoutingKernel
from flab2bp.spec import BeltTier, BuildSpec, MachineGroup, SelfLoopSeed

_BELT_RULES = catalog.BeltAltitudeRules(
    max_z=catalog.belt_max_z(catalog.DEFAULT_LAB_LEVEL),
    vertical_construction=True,
    storage_level=catalog.DEFAULT_STORAGE_LEVEL,
    lab_level=catalog.DEFAULT_LAB_LEVEL,
    from_url=False,
)


def test_different_flight_levels_retain_riser_and_shared_column_contacts() -> None:
    left = set(solver.cells(((-2, 0, 0), (-2, 0, 2), (2, 0, 2), (2, 0, 0))))
    right = set(solver.cells(((-2, 0, 0), (-2, 0, 4), (0, 0, 4), (0, 0, 0))))
    left_off_level = {cell for cell in left if cell[2] != 2}
    right_off_level = {cell for cell in right if cell[2] != 4}
    expected = {(-2, 0, 0), (-2, 0, 1), (-2, 0, 2), (0, 0, 2)}

    assert (
        solver._overlapping_cells(left, right, left_off_level, right_off_level, same_level=False)
        == expected
    )
    assert (
        solver._overlapping_cells(right, left, right_off_level, left_off_level, same_level=False)
        == expected
    )


def test_selected_run_contacts_survive_shared_line_removal_and_restoration() -> None:
    original: list[tuple[paths.Cell, ...]] = [
        ((-2, 0, 3), (2, 0, 3)),
        ((-2, 0, 3), (2, 0, 3)),
        ((0, 0, 0), (0, 0, 5)),
        ((2, 0, 3), (2, 2, 3)),
        ((-2, 0, 4), (2, 0, 4)),
    ]
    routes = list(original)
    budget = WorkBudget(monotonic() + 10)
    index = solver._SelectedRuns(len(routes))

    def contacts(changed: list[bool]) -> set[tuple[int, int]]:
        geometries = [
            paths._geometry(
                paths.FixedPath(
                    points,
                    paths.Endpoint(points[0], (1, 0), 2 * owner),
                    paths.Endpoint(points[-1], (-1, 0), 2 * owner + 1),
                    f"item-{owner}",
                ),
                budget,
            )
            for owner, points in enumerate(routes)
        ]
        return set(index.pairs(geometries, changed, budget))

    assert contacts([True] * 5) == {
        (0, 1),
        (0, 2),
        (0, 3),
        (1, 2),
        (1, 3),
        (2, 4),
    }

    # Removing one owner must not remove the other owner of the same line.
    routes[0] = ((-2, 8, 3), (2, 8, 3))
    assert contacts([True, False, False, False, False]) == set()
    routes[2] = ((2, 0, 0), (2, 0, 5))
    assert contacts([False, False, True, False, False]) == {(1, 2), (2, 3), (2, 4)}

    routes[0], routes[2] = original[0], original[2]
    assert contacts([True, False, True, False, False]) == {
        (0, 1),
        (0, 2),
        (0, 3),
        (1, 2),
        (2, 4),
    }
    assert contacts([False] * 5) == set()
    assert contacts([False, False, True, False, False]) == {(0, 2), (1, 2), (2, 4)}


def test_ranked_output_transfer_stays_outside_the_machine_edge() -> None:
    # Higher-ranked outputs leave eastward; the westward input-collector
    # detour would turn this path back through the neighboring machine body.
    flight = Flight(
        Terminal(rd._Port(0, 0, 0), (1, 0)),
        Terminal(rd._Port(1, 4, 10), (-1, 0)),
        "iron-ingot",
        Fraction(1),
        2,
        4,
        "local-source",
    )
    occupied = occupied_cells(path_through(flight.points(2)))
    machine_edge = {(-1, y, z) for y in range(11) for z in range(3)}
    assert occupied.isdisjoint(machine_edge)
    assert {(0, 0, 0), (4, 10, 0)} <= occupied


def test_static_rejections_preserve_legal_heights_of_partial_adapter_rows() -> None:
    obligation = paths.Obligation(
        0,
        "iron-ingot",
        Fraction(1),
        paths.Endpoint((0, 0, 0), (1, 0), 0),
        paths.Endpoint((12, 4, 0), (-1, 0), 1),
    )
    budget = WorkBudget(monotonic() + 10)
    domains = paths.domains(
        paths.TemplateProblem((obligation,), frozenset(), (), (), (), (3, 4)),
        budget,
    )
    with Cadical195(use_timer=False) as sat:
        factors = FactorCNF(domains, sat.add_clause, budget)
        # Both heights of XY row zero are blocked; only the upper height of row
        # one is blocked. Compressing a full row must not drop that distinction.
        factors.exclude_mask(0, 0b1011)
        for candidate in range(6):
            combo, height = divmod(candidate, 2)
            feasible = sat.solve(assumptions=[factors.xy[0][combo], factors.height[0][height]])
            assert feasible is (candidate in (2, 4, 5))


def test_overflight_clears_projected_corner_that_flat_height_misses() -> None:
    machine = colliders.Placed(376, 0.0, 0.0, 0.0, 0.0)
    boxes = colliders.target_boxes(machine, *colliders.preview_pose(0.0, 0.0, 0.0, 0.0))

    def overlaps(level: int) -> bool:
        position, _ = colliders.preview_pose(-3.0, -1.0, level, 0.0)
        scale = 1 + colliders.BELT_PROBE_LIFT / math.hypot(*position)
        probe = (position[0] * scale, position[1] * scale, position[2] * scale)
        return any(
            colliders.sphere_box_overlap(probe, colliders.BELT_PROBE_RADIUS, box) for box in boxes
        )

    flat_level = math.floor(colliders.belt_crossing_height(machine.model_index)) + 1
    assert overlaps(flat_level)
    assert not overlaps(spherical_overflight_limit(machine.model_index, Fraction(0)))


def test_seeded_return_survives_competing_import_of_the_same_item() -> None:
    # X-ray cracking must recycle 1/2 hydrogen/s and export its 1/4 surplus.
    # Supplying its input from the unrelated import instead balances the global
    # rates but removes the physical return that the hand-prime contract needs.
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="x-ray-cracking",
                machine_item_id="oil-refinery",
                count=1,
                inputs_per_machine={"hydrogen": Fraction(1, 2), "refined-oil": Fraction(1, 2)},
                outputs_per_machine={
                    "hydrogen": Fraction(3, 4),
                    "energetic-graphite": Fraction(1, 4),
                },
            ),
            MachineGroup(
                recipe_id="deuterium",
                machine_item_id="miniature-particle-collider",
                count=1,
                inputs_per_machine={"hydrogen": Fraction(5, 2)},
                outputs_per_machine={"deuterium": Fraction(5, 4)},
            ),
        ),
        external_inputs={"hydrogen": Fraction(9, 4), "refined-oil": Fraction(1, 2)},
        outputs={"deuterium": Fraction(5, 4), "energetic-graphite": Fraction(1, 4)},
        self_loop_seeds=(
            SelfLoopSeed(
                item_id="hydrogen",
                recipe_id="x-ray-cracking",
                machine_item_id="oil-refinery",
                machines=1,
                consumed_per_craft=Fraction(2),
                produced_per_craft=Fraction(3),
                net_per_craft=Fraction(1),
                seed_items=2,
            ),
        ),
    )
    placement = TransportRoutingKernel(
        belt_rules=_BELT_RULES, band_policy=BandPolicy("portable")
    ).lay_out(spec, time_budget_s=15)
    report = validate.certify(placement, spec, belt_rules=_BELT_RULES, expect_power=True)
    assert report.ok, report.errors
    assert not report.skipped
    assert set(self_loop_prime_heads(placement, spec)) == {"hydrogen"}


def test_sharded_producer_can_export_its_surplus_after_feeding_a_consumer() -> None:
    # The one-output-port exchanger splits internal and external destinations
    # across strips. Its internal shard produces more than the discharge mode
    # consumes; that surplus must remain eligible for the external boundary.
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="accumulator-full",
                machine_item_id="energy-exchanger",
                count=3,
                inputs_per_machine={"accumulator": Fraction(1, 4)},
                outputs_per_machine={"accumulator-full": Fraction(1, 4)},
            ),
            MachineGroup(
                recipe_id="accumulator-discharge",
                machine_item_id="energy-exchanger",
                count=1,
                inputs_per_machine={"accumulator-full": Fraction(1, 8)},
                outputs_per_machine={"accumulator": Fraction(1, 8)},
            ),
        ),
        external_inputs={"accumulator": Fraction(5, 8)},
        outputs={"accumulator-full": Fraction(5, 8)},
    )
    budget = WorkBudget(monotonic() + 15)
    inventory = prepare_inventory(spec, _BELT_RULES, BandPolicy("portable"), budget)
    selected = select_topology(spec, inventory, "captured", budget)
    exports = [
        demand
        for demand in selected.inventory.demands
        if demand.item == "accumulator-full" and demand.sink is None
    ]
    assert sum((selected.rates[demand.ordinal] for demand in exports), Fraction()) == Fraction(5, 8)
    assert {demand.source.strip for demand in exports if demand.source is not None} == {
        index
        for index, strip in enumerate(inventory.strips)
        if strip.recipe_id == "accumulator-full"
    }
    discharge = sum(
        (
            selected.rates[demand.ordinal]
            for demand in selected.inventory.demands
            if demand.item == "accumulator-full" and demand.sink is not None
        ),
        Fraction(),
    )
    assert discharge == Fraction(1, 8)


def test_native_routes_upgrade_above_floor_without_exceeding_allowed_ceiling() -> None:
    # One 7/s lane fits the allowed Mk.II ceiling, but not its emitted Mk.I floor.
    # Omitting canonical retiering makes the physical capacity certificate fail.
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=7,
                inputs_per_machine={"iron-ore": Fraction(1)},
                outputs_per_machine={"iron-ingot": Fraction(1)},
            ),
        ),
        external_inputs={"iron-ore": Fraction(7)},
        outputs={"iron-ingot": Fraction(7)},
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=Fraction(6),
        belt_upgrades=(BeltTier(item_id="conveyor-belt-2", items_per_second=Fraction(12)),),
    )
    placement = TransportRoutingKernel(
        belt_rules=_BELT_RULES, band_policy=BandPolicy("portable")
    ).lay_out(spec, time_budget_s=15)
    report = validate.certify(placement, spec, belt_rules=_BELT_RULES, expect_power=True)
    assert report.ok, report.errors
    assert not report.skipped
    belt_items = {
        building.item_id for building in placement.buildings if catalog.is_belt(building.item_id)
    }
    assert 2002 in belt_items
    assert belt_items <= {2001, 2002}


def test_changed_routes_clear_conflicts_without_invalidating_unchanged_routes() -> None:
    obligations = tuple(
        paths.Obligation(
            index,
            f"item-{index}",
            Fraction(1),
            paths.Endpoint((0, 4 * index, 0), (1, 0), 2 * index),
            paths.Endpoint((12, destination_y, 0), (-1, 0), 2 * index + 1),
        )
        for index, destination_y in enumerate((8, 0, 12, 4))
    )
    problem = paths.TemplateProblem(obligations, frozenset(), (), (4, 8), (-4, 16), (3, 4))
    budget = WorkBudget(monotonic() + 10)
    selected = solver.select(problem, budget)
    assert set(selected) == {obligation.ordinal for obligation in obligations}
    routes = [
        paths.FixedPath(
            selected[obligation.ordinal],
            obligation.source,
            obligation.sink,
            obligation.item,
        )
        for obligation in obligations
    ]
    assert all(paths.compatible(first, second, budget) for first, second in combinations(routes, 2))


def test_foreign_flight_avoids_unused_splitter_dock_while_used_docks_remain_live() -> None:
    constructor = TemplateConstructor(
        BuildSpec(groups=()), _BELT_RULES, RoutingRun(WorkBudget(monotonic() + 15))
    )
    node = constructor.splitter(0, 0, "iron-ingot")
    inlet = constructor.dock(node, (-1, 0), feed=True)
    outlet = constructor.dock(node, (1, 0), feed=False)
    left = constructor.belt((-3, 0, 0), "iron-ingot")
    right = constructor.belt((3, 0, 0), "iron-ingot")
    constructor.connect(
        left, inlet.port, [(-3, 0, 0), (0, 0, 0)], "iron-ingot", Fraction(1), "local-input"
    )
    constructor.connect(
        outlet.port, right, [(0, 0, 0), (3, 0, 0)], "iron-ingot", Fraction(1), "local-output"
    )
    # Two elevated obstacles deny the short straight risers. Without the
    # splitter's foreign keepout, the longer adapter takes its unused south
    # dock at both ground and the next altitude. A lateral adapter is legal.
    constructor.belt((-4, -1, 1), "stone")
    constructor.belt((-2, -1, 1), "stone")
    source = constructor.belt((-6, -1, 0), "copper-ingot")
    sink = constructor.belt((6, -1, 0), "copper-ingot")
    constructor.flight(
        Terminal(source, (1, 0)),
        Terminal(sink, (-1, 0)),
        "copper-ingot",
        Fraction(1),
        3,
        0,
        "internal",
    )
    constructor.finish()
    foreign = occupied_cells(constructor.selected_points[0])
    assert foreign.isdisjoint(junction.keepout_cells(0, 0, 0))
    placement = Placement(buildings=assign_sorter_slots(constructor.canvas.buildings))
    finalize.finalize_placement(placement, BandPolicy("200"))
