from __future__ import annotations

import math
from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog, splitter_ports
from flab2bp.layout import routing_domain, slots, validate
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.route_feedback import DetailedRouteStatus, NetId, NetRole
from flab2bp.layout.route_primitives import RoutePrimitives


def test_locked_save_routes_and_emits_real_parallel_height_connector() -> None:
    canvas = routing_domain._Canvas(
        belt_rules=replace(
            routing_domain._DEFAULT_BELT_RULES,
            max_z=Fraction(1),
            vertical_construction=False,
        )
    )
    start, goal = (0, 1, 0), (0, 1, 1)
    bounds = (-1, -1, 1, 1)
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 3, 3), {})
    primitives = RoutePrimitives(canvas.belt_rules)
    edges = primitives.edges(
        canvas, grid, [start], {goal}, forbidden=(), active_paths={}, deadline=None
    )
    result = routing_domain._astar(
        canvas,
        [start],
        {goal},
        {},
        1.0,
        bounds,
        grid=grid,
        extra_edges=edges,
    )
    assert result.path == (start, goal)
    (candidate,) = primitives.on_path(result.path)
    assert candidate.stack_members[-1].model_index == 39
    belt_model = catalog.building(2002).model_index
    source = canvas.add(PlacedBuilding(2002, belt_model, *start[:2], Fraction(start[2])))
    target = canvas.add(PlacedBuilding(2002, belt_model, *goal[:2], Fraction(goal[2])))
    primitives.emit(canvas, candidate, source, target, 2002, belt_model, "iron-ore")
    assert splitter_ports.placement_issues(canvas.buildings) == ()
    assert primitives.altitudes(result.path, ramped=True) == [Fraction(0), Fraction(1)]
    # Attachment records share the anchor in layout space, but both real
    # carry altitudes must be unavailable to subsequent world-occupancy probes.
    assert not canvas.free_world(0, 0, Fraction(0))
    assert not canvas.free_world(0, 0, Fraction(1))


@pytest.mark.parametrize(
    ("start", "goal"),
    (
        ((0, 1, 0), (0, 1, 1)),
        ((0, 1, 1), (0, 1, 0)),
        ((0, 1, 2), (0, 1, 3)),
        ((0, 1, 3), (0, 1, 2)),
    ),
)
def test_foreign_reservation_blocks_connector_body_and_owner_release_restores_it(
    start: tuple[int, int, int], goal: tuple[int, int, int]
) -> None:
    canvas = routing_domain._Canvas(
        belt_rules=replace(
            routing_domain._DEFAULT_BELT_RULES,
            max_z=Fraction(3),
            vertical_construction=False,
            storage_level=2,
        )
    )
    bounds = (-1, -1, 1, 1)
    grid = routing_domain._make_grid(canvas, bounds, (-3, -3, 3, 3), {})
    primitives = RoutePrimitives(canvas.belt_rules)

    def available() -> bool:
        edges = primitives.edges(
            canvas, grid, [start], {goal}, forbidden=(), active_paths={}, deadline=None
        )
        return any(target == grid.index(goal) for target, _cost in edges.get(grid.index(start), ()))

    assert available()
    body = next(
        cell
        for cell in primitives.witnesses[start, goal].foreign_keepout
        if cell not in (start, goal)
    )
    owner = (91, 92, 0)
    canvas.reserved[body] = owner
    assert not available()
    canvas.routing_ports = frozenset((owner,))
    assert available()


def test_selected_connector_cannot_return_through_its_own_support() -> None:
    canvas = routing_domain._Canvas(
        belt_rules=replace(
            routing_domain._DEFAULT_BELT_RULES,
            max_z=Fraction(1),
            vertical_construction=False,
        )
    )
    start, goal = (0, 1, 0), (0, 1, 1)
    grid = routing_domain._make_grid(canvas, (-1, -1, 1, 1), (-3, -3, 3, 3), {})
    primitives = RoutePrimitives(canvas.belt_rules)
    primitives.edges(canvas, grid, [start], {goal}, forbidden=(), active_paths={}, deadline=None)
    candidate = primitives.witnesses[start, goal]
    body = next(cell for cell in candidate.foreign_keepout if cell not in (start, goal))
    assert primitives.path_is_clear((start, goal))
    assert not primitives.path_is_clear((body, start, goal))


def test_late_foreign_boundary_route_avoids_emitted_non_dock_body() -> None:
    canvas = routing_domain._Canvas(
        belt_rules=replace(
            routing_domain._DEFAULT_BELT_RULES,
            max_z=Fraction(1),
            vertical_construction=False,
        )
    )
    start, goal = (0, 1, 0), (0, 1, 1)
    grid = routing_domain._make_grid(canvas, (-1, -1, 1, 1), (-3, -3, 3, 3), {})
    primitives = RoutePrimitives(canvas.belt_rules)
    primitives.edges(canvas, grid, [start], {goal}, forbidden=(), active_paths={}, deadline=None)
    candidate = primitives.witnesses[start, goal]
    body = (0, -1, 1)
    assert body in candidate.foreign_keepout
    assert canvas.free(body)
    belt_model = catalog.building(2002).model_index
    source = canvas.add(
        PlacedBuilding(2002, belt_model, 0, 1, Fraction(0), carries_item="iron-ore")
    )
    target = canvas.add(
        PlacedBuilding(2002, belt_model, 0, 1, Fraction(1), carries_item="iron-ore")
    )
    # Emission runs after _finish has removed temporary search guards.
    primitives.emit(canvas, candidate, source, target, 2002, belt_model, "iron-ore")

    late_source = canvas.add(
        PlacedBuilding(
            2002,
            belt_model,
            -3,
            -1,
            Fraction(1),
            carries_item="copper-ore",
        )
    )
    port = routing_domain._Port(late_source, -3, -1, -3, -3, z=1)
    identity = NetId(None, 0, "copper-ore", NetRole.EXTERNAL, 0)
    net = routing_domain._Net(
        src=port,
        dst=port,
        item="copper-ore",
        net_id=identity,
        boundary_goals=((3, -1, 1),),
    )
    first_late_belt = len(canvas.buildings)
    result = routing_domain._route_boundary_nets(
        canvas,
        (net,),
        2002,
        belt_model,
        (-3, -1, 0, -1),
        outward=True,
    )
    assert result.status is DetailedRouteStatus.ROUTED
    assert result.routed == (identity,)
    # The direct elevated row crosses the unused rear arm. It must detour,
    # not exploit the absence of an anchor or dock belt on that body cell.
    assert all(
        (belt.x, belt.y, belt.z) not in candidate.foreign_keepout
        for belt in canvas.buildings[first_late_belt:]
    )
    assert not canvas.free(body)
    late_grid = routing_domain._make_grid(canvas, (-3, -3, 3, 3), (-5, -5, 5, 5), {})
    assert not late_grid.occ[late_grid.index(body)]
    assert splitter_ports.placement_issues(canvas.buildings) == ()
    report = validate.validate(
        Placement(tuple(slots.assign_belt_slots(canvas.buildings))),
        only=["game.belt_collide", "geom.belt_single_occupancy"],
        expect_power=False,
    )
    assert not report.errors, "\n".join(finding.message for finding in report.errors)


def test_boundary_dock_power_does_not_admit_an_uncovered_splitter_stack() -> None:
    canvas = routing_domain._Canvas(
        belt_rules=replace(
            routing_domain._DEFAULT_BELT_RULES,
            max_z=Fraction(3),
            vertical_construction=False,
            storage_level=2,
        )
    )
    start, goal = (0, 1, 2), (0, 1, 3)
    grid = routing_domain._make_grid(canvas, (-1, 1, 1, 1), (-3, -1, 3, 3), {})
    primitives = RoutePrimitives(canvas.belt_rules)
    primitives.edges(canvas, grid, [start], {goal}, forbidden=(), active_paths={}, deadline=None)
    candidate = primitives.witnesses[start, goal]
    tower = canvas.power_building
    outside_site = (0, math.floor(tower.cover_radius) + 1)
    discs = routing_domain._power_coverage_discs((), (outside_site,), tower=tower)
    belt_model = catalog.building(2002).model_index
    docks = (
        PlacedBuilding(2002, belt_model, 0, 1, Fraction(2)),
        PlacedBuilding(2002, belt_model, 0, 1, Fraction(3)),
    )
    assert routing_domain._buildings_are_powered(docks, discs)
    assert not routing_domain._buildings_are_powered(candidate.stack_members, discs)

    def available() -> bool:
        edges = primitives.edges(
            canvas,
            grid,
            [start],
            {goal},
            forbidden=(),
            active_paths={},
            deadline=None,
            power_allows=lambda member: routing_domain._buildings_are_powered((member,), discs),
        )
        return any(target == grid.index(goal) for target, _cost in edges.get(grid.index(start), ()))

    assert not available()
    discs = routing_domain._power_coverage_discs((), (outside_site, (0, -2)), tower=tower)
    assert routing_domain._buildings_are_powered(candidate.stack_members, discs)
    assert available()
    source, target = (canvas.add(dock) for dock in docks)
    primitives.emit(canvas, candidate, source, target, 2002, belt_model, "iron-ore")
    canvas.add(
        PlacedBuilding(
            tower.item_id,
            tower.model_index,
            0,
            -2,
            width=tower.width,
            height=tower.height,
        ),
        solid=True,
    )
    report = validate.validate(Placement(tuple(canvas.buildings)), only=["power.coverage"])
    assert not report.errors, "\n".join(finding.message for finding in report.errors)


def _projection_workspace(
    bounds: tuple[int, int, int, int], additions: tuple[PlacedBuilding, ...] = ()
) -> routing_domain._Canvas:
    x0, y0, x1, y1 = bounds
    columns = (x1 - x0 + 9) // 10
    rows = (y1 - y0 + 9) // 10
    xs = [x0 + (x1 - x0) * index // columns for index in range(columns + 1)]
    ys = [y0 + (y1 - y0) * index // rows for index in range(rows + 1)]
    sites = tuple(
        sorted({*((x, y) for x in xs for y in (y0, y1)), *((x, y) for y in ys for x in (x0, x1))})
    )
    prepared = routing_domain._PreparedRoutingProblem(
        building_templates=additions,
        blocked=(),
        solid=frozenset(),
        reserved=(),
        port_corridors=(),
        keep_out=frozenset(),
        guard=frozenset(),
        nets=(),
        core=bounds,
        route_bounds=bounds,
        limit=bounds,
        power_sites=sites,
        sorters=0,
        coaters=len(additions),
        direct_inserts=0,
        belt_rules=replace(
            routing_domain._DEFAULT_BELT_RULES, max_z=Fraction(1), vertical_construction=False
        ),
    )
    return prepared.new_workspace().canvas


def test_prepared_workspace_admits_projected_coater_geometry_without_source_siblings() -> None:
    bounds = (0, 0, 42, 34)
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    canvas = _projection_workspace(
        bounds,
        (PlacedBuilding(coater.item_id, coater.model_index, 26, 15, yaw=90.0),),
    )
    primitives = RoutePrimitives(canvas.belt_rules)
    grid = routing_domain._make_grid(canvas, bounds, bounds, {})

    def available(y: int) -> bool:
        start, goal = (25, y + 1, 1), (26, y, 0)
        edges = primitives.edges(
            canvas, grid, [start], {goal}, forbidden=(), active_paths={}, deadline=None
        )
        return any(target == grid.index(goal) for target, _cost in edges.get(grid.index(start), ()))

    assert not available(17)
    assert available(18)


def test_source_and_connector_admission_share_one_projected_selection() -> None:
    bounds = (0, -4, 179, 74)
    canvas = _projection_workspace(bounds)
    primitives = RoutePrimitives(canvas.belt_rules)
    grid = routing_domain._make_grid(canvas, bounds, bounds, {})
    start, goal = (45, 1, 1), (46, 0, 0)

    def available(taps: tuple[tuple[int, int, int], ...] = ()) -> bool:
        edges = primitives.edges(
            canvas,
            grid,
            [start],
            {goal},
            forbidden=(),
            active_paths={},
            active_taps=taps,
            deadline=None,
        )
        return any(target == grid.index(goal) for target, _cost in edges.get(grid.index(start), ()))

    assert available()
    candidate = primitives.witnesses[start, goal]
    assert canvas.junction_is_clear(43, 0, 1)
    assert not canvas.junction_is_clear(43, 0, 1, selected=candidate.stack_members)
    assert canvas.junction_is_clear(42, 0, 1, selected=candidate.stack_members)
    assert not available(((43, 0, 1),))
    assert available(((42, 0, 1),))
    assert available()


def test_commit_refuses_a_jointly_invalid_source_and_connector_before_emission() -> None:
    bounds = (0, -4, 179, 74)
    canvas = _projection_workspace(bounds)
    primitives = RoutePrimitives(canvas.belt_rules)
    grid = routing_domain._make_grid(canvas, bounds, bounds, {})
    start, goal = (45, 1, 1), (46, 0, 0)
    primitives.edges(canvas, grid, [start], {goal}, forbidden=(), active_paths={}, deadline=None)
    assert (start, goal) in primitives.witnesses
    belt_model = catalog.building(2002).model_index

    def port(x: int, y: int, z: int) -> routing_domain._Port:
        index = canvas.add(
            PlacedBuilding(2002, belt_model, x, y, Fraction(z), carries_item="iron-ore")
        )
        return routing_domain._Port(index, x, y, x, x, z=z)

    source, destination = port(45, 2, 1), port(47, 0, 0)
    tap, branch_destination = port(43, 0, 1), port(41, 0, 0)
    onward = port(43, 1, 1)
    canvas.buildings[tap.belt] = replace(canvas.buildings[tap.belt], output_obj=onward.belt)
    nets = [
        routing_domain._Net(src=source, dst=destination, item="iron-ore"),
        routing_domain._Net(src=tap, dst=branch_destination, item="iron-ore"),
    ]
    paths = {0: (start, goal), 1: ((42, 0, 0),)}
    unlinked = routing_domain._commit_paths(
        canvas,
        nets,
        paths,
        2002,
        belt_model,
        primitives=primitives,
        source_taps={1: (43, 0, 1)},
    )
    assert unlinked == (0, 1)
    assert not any(building.item_id == catalog.SPLITTER_ID for building in canvas.buildings)
