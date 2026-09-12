"""Physical regressions retained from the staged mall-routing repairs."""

from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout import routing_domain as domain
from flab2bp.layout import validate
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.route_feedback import Cell, DetailedRouteStatus, NetId, NetRole


def _power_canvas(distance: int, *, blocked: bool = False) -> domain._Canvas:
    canvas = domain._Canvas(limit=(-8, -8, distance + 8, 8))
    tower = canvas.power_building
    for x in (0, distance):
        canvas.add(
            PlacedBuilding(
                tower.item_id, tower.model_index, x, 0, width=tower.width, height=tower.height
            ),
            solid=True,
        )
    if blocked:
        for x in range(3, distance - 2):
            for y in range(-8, 9):
                canvas.add(PlacedBuilding(2003, 37, x, y, z=Fraction(2)))
    return canvas


def _power_context(canvas: domain._Canvas) -> validate.Context:
    return validate._context(
        Placement(tuple(canvas.buildings)),
        None,
        None,
        10000,
        canvas.belt_rules.max_z,
        canvas.belt_rules.vertical_construction,
    )


@pytest.mark.parametrize("distance", (40, 100))
def test_covered_power_islands_are_physically_joined(distance: int) -> None:
    canvas = _power_canvas(distance)
    before = _power_context(canvas)
    assert tuple(validate._coverage(before)) == ()
    assert tuple(validate._connectivity(before))

    sites, uncovered = domain.plan_power_infill(canvas)
    assert uncovered == ()
    domain._place_power(canvas, sites)
    after = _power_context(canvas)
    assert tuple(validate._connectivity(after)) == ()
    assert tuple(validate._coverage(after)) == ()
    assert tuple(validate._power_too_close(after)) == ()


def test_elevated_route_wall_refuses_power_relays_without_mutation() -> None:
    canvas = _power_canvas(100, blocked=True)
    before = tuple(canvas.buildings)
    with pytest.raises(domain._Unpowerable, match="power.connectivity"):
        domain.plan_power_infill(canvas)
    assert tuple(canvas.buildings) == before


def test_cancelled_power_planning_does_not_emit_relays() -> None:
    canvas = _power_canvas(100)
    before = tuple(canvas.buildings)
    with pytest.raises(domain._PreparationDeadline):
        domain.plan_power_infill(canvas, cancelled=lambda: True)
    assert tuple(canvas.buildings) == before


@pytest.mark.parametrize("select_splitter", (False, True))
def test_direct_carry_head_merge_respects_selected_splitter(select_splitter: bool) -> None:
    canvas = domain._Canvas(limit=(-8, -8, 10, 10))

    def belt(x: int, y: int, output: int | None = None) -> int:
        return canvas.add(
            PlacedBuilding(
                2001,
                35,
                x,
                y,
                carries_item="gear",
                output_obj=output,
            )
        )

    def port(index: int, x: int, y: int) -> domain._Port:
        return domain._Port(index, x, y, x, x)

    source = belt(0, 0)
    belt(0, -1, source)
    foreign_source = belt(-2, 2)
    destination = belt(6, 1)
    branch_destination = belt(-4, -2)
    shared = port(source, 0, 0)
    target = port(destination, 6, 1)
    nets = [
        domain._Net(shared, target, "gear"),
        domain._Net(shared, port(branch_destination, -4, -2), "gear"),
        domain._Net(port(foreign_source, -2, 2), target, "gear"),
    ]
    paths: dict[int, tuple[Cell, ...]] = {
        0: ((0, 1, 0), (1, 1, 0), (2, 1, 0), (3, 1, 0), (4, 1, 0), (5, 1, 0)),
        1: ((-1, 0, 0), (-2, 0, 0), (-3, 0, 0), (-3, -1, 0), (-3, -2, 0)),
        2: ((-1, 2, 0), (-1, 1, 0)),
    }
    if not select_splitter:
        paths.pop(1)
    unlinked = domain._commit_paths(
        canvas,
        nets,
        paths,
        2001,
        35,
        src_group={0: (1,), 1: (0,), 2: ()},
        dst_group={0: (2,), 1: (), 2: (0,)},
        source_taps={1: (0, 0, 0)} if select_splitter else {},
        sink_hints={2: (0, 1, 0)},
    )
    assert unlinked == ((2,) if select_splitter else ())
    carry_head = canvas.blocked[0, 1, 0]
    predecessors = canvas.buildings.by_output_obj(carry_head)
    assert len(predecessors) == (1 if select_splitter else 2)
    if select_splitter:
        feeder = canvas.buildings[predecessors[0]]
        assert feeder.input_obj is not None
        assert canvas.buildings[feeder.input_obj].item_id == catalog.SPLITTER_ID


def test_capacity_frontier_charges_inherited_prefix_and_suffix() -> None:
    paths: dict[int, tuple[Cell, ...]] = {
        0: tuple((x, 0, 0) for x in range(6)),
        1: ((2, 1, 0), (3, 1, 0)),
        2: ((4, 2, 0), (4, 1, 0)),
    }
    owners = {cell: index for index, path in paths.items() for cell in path}
    sources, sinks = domain._flow_frontier_ranges(
        3,
        paths,
        owners,
        {1: (2, 0, 0)},
        {2: (4, 0, 0)},
        domain.RoutingFlowLimits(
            (Fraction(3), Fraction(4), Fraction(4), Fraction(4)), Fraction(10)
        ),
    )
    canvas = domain._Canvas(limit=(-2, -2, 8, 4))
    canvas.blocked.update({cell: domain._TENTATIVE for cell in owners})
    assert sources[0] == (0, 0)
    provenance: dict[Cell, Cell] = {}
    domain._merge_frontier(canvas, paths, (0,), provenance=provenance, path_ranges=sinks)
    assert provenance == {}


def test_overhead_prices_congestion_without_turning_it_into_a_wall() -> None:
    from flab2bp.layout.projection_world import GeometricWorld
    from flab2bp.layout.routing_proposals import overhead_path

    canvas = domain._Canvas(belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(0)))
    world = GeometricWorld(canvas, history={(4, 0, 0): 40}, pressure=0.5)
    assert overhead_path(world, [(0, 0, 0)], {(4, 0, 0)}, (0, 0, 4, 0), None) == tuple(
        (x, 0, 0) for x in range(5)
    )
    canvas.guard.add((2, 0, 0))
    assert overhead_path(world, [(0, 0, 0)], {(4, 0, 0)}, (0, 0, 4, 0), None) is None


def test_overhead_dogleg_connects_when_both_corner_routes_are_blocked() -> None:
    from flab2bp.layout.projection_world import GeometricWorld
    from flab2bp.layout.routing_proposals import overhead_path

    canvas = domain._Canvas(belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(0)))
    canvas.guard.update({(3, 0, 0), (0, 3, 0)})
    path = overhead_path(GeometricWorld(canvas), [(0, 0, 0)], {(4, 4, 0)}, (0, 0, 4, 4), None)
    assert path is not None
    assert path[0] == (0, 0, 0) and path[-1] == (4, 4, 0)
    assert not canvas.guard.intersection(path)


def test_overhead_blocked_nearest_start_does_not_starve_clear_alternative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout import routing_proposals
    from flab2bp.layout.projection_world import GeometricWorld

    canvas = domain._Canvas(belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(5)))
    canvas.guard.update((-1, y, z) for y in range(-4, 5) for z in range(canvas.levels))
    remaining = 256

    def bounded_work(_deadline: float | None) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining <= 0:
            raise routing_proposals.Deadline

    # A deterministic query allowance: the unreachable nearest endpoint must
    # not consume every construction opportunity before the clear alternative.
    monkeypatch.setattr(routing_proposals, "check_deadline", bounded_work)
    path = routing_proposals.overhead_path(
        GeometricWorld(canvas),
        [(-2, 0, 0), (0, 3, 0)],
        {(0, 0, 0)},
        (-4, -4, 4, 4),
        None,
    )
    assert path == ((0, 3, 0), (0, 2, 0), (0, 1, 0), (0, 0, 0))


def test_rejected_ramp_approaches_do_not_starve_other_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout import routing_proposals
    from flab2bp.layout.projection_world import GeometricWorld

    canvas = domain._Canvas(belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(1)))
    canvas.guard.update((-1, y, 0) for y in range(-32, 37))
    canvas.guard.update((10, y, 0) for y in range(5))
    for x in range(-32, 0):
        canvas.belt_ban[(x, 0)] = {1}
    for y in range(-32, 37):
        canvas.belt_ban[(-4, y)] = {1}
    remaining = 512

    def bounded_work(_deadline: float | None) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining <= 0:
            raise routing_proposals.Deadline

    # Both starts are clear. The nearest start's ceiling rejects its ramp
    # approaches; the farther start can cross its ground wall overhead.
    monkeypatch.setattr(routing_proposals, "check_deadline", bounded_work)
    path = routing_proposals.overhead_path(
        GeometricWorld(canvas),
        [(-4, 0, 0), (20, 0, 0)],
        {(0, 4, 0)},
        (-32, -32, 24, 36),
        None,
    )
    assert path is not None
    assert path[0] == (20, 0, 0) and path[-1] == (0, 4, 0)
    assert any(cell[2] == 1 for cell in path)
    assert not canvas.guard.intersection(path)


def test_overhead_keeps_searching_after_consumer_rejects_a_proposal() -> None:
    from flab2bp.layout.projection_world import GeometricWorld
    from flab2bp.layout.routing_proposals import overhead_path

    canvas = domain._Canvas(belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(0)))
    world = GeometricWorld(canvas)
    path = overhead_path(
        world,
        [(0, 0, 0)],
        {(4, 4, 0)},
        (0, 0, 4, 4),
        None,
        admit_proposal=lambda candidate, _deadline: (0, 4, 0) in candidate,
    )
    assert path is not None and (0, 4, 0) in path
    assert path[0] == (0, 0, 0) and path[-1] == (4, 4, 0)
    assert (
        overhead_path(
            world,
            [(0, 0, 0)],
            {(4, 4, 0)},
            (0, 0, 4, 4),
            None,
            admit_proposal=lambda candidate, _deadline: False,
        )
        is None
    )


def test_live_splitter_withholds_downstream_but_not_upstream_merges() -> None:
    paths: dict[int, tuple[Cell, ...]] = {
        0: tuple((x, 0, 0) for x in range(11)),
        1: ((5, -1, 0), (5, -2, 0)),
    }
    canvas = domain._Canvas(limit=(-1, -3, 12, 3))
    canvas.blocked.update({cell: domain._TENTATIVE for path in paths.values() for cell in path})
    offers = domain._merge_frontier(
        canvas,
        paths,
        (0,),
        protected_sinks=domain._protected_merge_cells(paths, (0,), {1: (5, 0, 0)}),
    )
    assert (5, 1, 0) not in offers
    assert (3, 1, 0) in offers


def test_complete_overhead_route_crosses_ground_wall_with_legal_ramps() -> None:
    from flab2bp.layout.projection_world import GeometricWorld
    from flab2bp.layout.routing_proposals import overhead_path

    canvas = domain._Canvas(
        limit=(0, 0, 16, 0),
        belt_rules=replace(
            domain._DEFAULT_BELT_RULES, max_z=Fraction(2), vertical_construction=False
        ),
    )
    canvas.guard.add((8, 0, 0))
    world = GeometricWorld(canvas)
    path = overhead_path(world, [(0, 0, 0)], {(16, 0, 0)}, (0, 0, 16, 0), None)
    assert path is not None
    assert path[0] == (0, 0, 0) and path[-1] == (16, 0, 0)
    assert (8, 0, 0) not in path
    altitudes = domain._altitude_profile(path, ramped=canvas.ramped)
    assert altitudes is not None
    for index, cell in enumerate(path[1:], 1):
        previous = path[index - 1]
        assert domain._legal_link(
            *previous[:2],
            altitudes[index - 1],
            *cell[:2],
            altitudes[index],
            ramped=canvas.ramped,
        )


def test_source_body_rejection_keeps_other_ordinary_taps_available() -> None:
    """A nearby tap blocks both goal docks; an upstream tap can still feed them."""
    bounds = (-3, -5, 35, 8)
    canvas = domain._Canvas(limit=bounds)

    def port(x: int, y: int, level: int) -> domain._Port:
        index = canvas.add(PlacedBuilding(2003, 37, x, y, z=Fraction(level), carries_item="gear"))
        return domain._Port(index, x, y, x, x, z=level)

    source = port(0, 1, 3)
    trunk = port(30, 1, 3)
    below = port(15, 0, 0)
    canvas.guard.update(((14, 0, 0), (15, -1, 0)))
    nets = [
        domain._Net(
            source,
            destination,
            "gear",
            net_id=NetId(0, ordinal + 1, "gear", NetRole.INTERNAL, ordinal),
        )
        for ordinal, destination in enumerate((trunk, below))
    ]
    result = domain._route_all(
        canvas,
        nets,
        2003,
        37,
        bounds,
        budget={"left": 10_000},
        flow_limits=domain.RoutingFlowLimits((Fraction(1), Fraction(1)), Fraction(30)),
    )
    assert result.status is DetailedRouteStatus.ROUTED
    reached: set[int] = set()
    pending = [source.belt]
    while pending:
        index = pending.pop()
        if index in reached:
            continue
        reached.add(index)
        output = canvas.buildings[index].output_obj
        if output is not None:
            pending.append(output)
        pending.extend(canvas.buildings.by_input_obj(index))
    assert {trunk.belt, below.belt} <= reached


@pytest.mark.parametrize("foreign_belt", (False, True))
def test_supplied_head_can_branch_without_excusing_foreign_belts(foreign_belt: bool) -> None:
    bounds = (-4, -4, 8, 8)
    canvas = domain._Canvas(limit=bounds)

    def port(x: int, y: int) -> domain._Port:
        index = canvas.add(PlacedBuilding(2001, 35, x, y, carries_item="gear"))
        return domain._Port(index, x, y, x, x)

    source = port(0, 0)
    canvas.add(PlacedBuilding(2001, 35, -1, 0, carries_item="gear", output_obj=source.belt))
    destinations = (port(6, 0), port(1, 5))
    if foreign_belt:
        canvas.add(PlacedBuilding(2001, 35, 1, -1, carries_item="gear"))
    before = tuple(canvas.buildings)
    # Only the supplied path head can carry this family's required Splitter.
    # Its actual prebuilt feeder is within keepout; an unrelated belt is not
    # excused merely because it carries the same item.
    canvas.junction_ban.update(
        (x, y, level)
        for x in range(-4, 9)
        for y in range(-4, 9)
        for level in range(canvas.levels)
        if (x, y, level) != (1, 0, 0)
    )
    nets = [
        domain._Net(
            source,
            destination,
            "gear",
            net_id=NetId(0, index + 1, "gear", NetRole.INTERNAL, index),
        )
        for index, destination in enumerate(destinations)
    ]
    result = domain._route_all(
        canvas,
        nets,
        2001,
        35,
        bounds,
        budget={"left": 10_000},
        flow_limits=domain.RoutingFlowLimits((Fraction(1), Fraction(1)), Fraction(6)),
    )
    if foreign_belt:
        assert result.status is not DetailedRouteStatus.ROUTED
        assert tuple(canvas.buildings) == before
        return
    assert result.status is DetailedRouteStatus.ROUTED
    reached: set[int] = set()
    pending = [source.belt]
    while pending:
        index = pending.pop()
        if index in reached:
            continue
        reached.add(index)
        output = canvas.buildings[index].output_obj
        if output is not None:
            pending.append(output)
        pending.extend(canvas.buildings.by_input_obj(index))
    assert {destination.belt for destination in destinations} <= reached


def test_ordinary_routing_cannot_escape_the_composition_frame() -> None:
    from flab2bp.layout import finalize
    from flab2bp.layout.band_policy import BandPolicy

    bounds = (-2, -2, 202, 161)
    policy = BandPolicy("200")
    canvas = domain._Canvas(
        limit=bounds, belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(0))
    )
    tower = canvas.power_building
    for x, y in ((0, 0), (200, 159)):
        canvas.add(
            PlacedBuilding(
                tower.item_id, tower.model_index, x, y, width=tower.width, height=tower.height
            ),
            solid=True,
        )

    def port(x: int, y: int) -> domain._Port:
        index = canvas.add(PlacedBuilding(2003, 37, x, y, carries_item="gear"))
        return domain._Port(index, x, y, x, x)

    source, destination = port(50, 80), port(150, 80)
    canvas.guard.update((100, y, 0) for y in range(160))
    canvas.junction_projection = domain._CompositionProjection(
        canvas.buildings, bounds, policy, belt_rules=canvas.belt_rules
    )
    nets = [
        domain._Net(
            source,
            destination,
            "gear",
            net_id=NetId(0, 1, "gear", NetRole.INTERNAL, 0),
        )
    ]
    before = tuple(canvas.buildings)
    refused = domain._route_all(canvas, nets, 2003, 37, bounds, budget={"left": 100_000})
    assert refused.status is not DetailedRouteStatus.ROUTED
    assert tuple(canvas.buildings) == before

    canvas.guard.remove((100, 80, 0))
    accepted = domain._route_all(canvas, nets, 2003, 37, bounds, budget={"left": 100_000})
    assert accepted.status is DetailedRouteStatus.ROUTED
    x0, y0, x1, y1 = Placement(buildings=tuple(canvas.buildings)).bounds
    assert finalize.band_policy_search_envelope(policy, perimeter=0).frame_candidates(
        x1 - x0 + 1, y1 - y0 + 1
    )


def test_source_witness_rollback_preserves_another_routes_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Borrowing a sibling's branch dock must not open it to unrelated searches."""
    bounds = (-4, -8, 14, 8)
    canvas = domain._Canvas(limit=bounds)

    def port(x: int, y: int) -> domain._Port:
        index = canvas.add(PlacedBuilding(2001, 35, x, y, carries_item="gear"))
        return domain._Port(index, x, y, x, x)

    source = port(0, 0)
    canvas.add(PlacedBuilding(2001, 35, -1, 0, carries_item="gear", output_obj=source.belt))
    destinations = (port(12, 0), port(1, 6), port(1, -6))
    # The first route must promise a downstream Splitter. The next route
    # borrows its guarded dock while proving access for the final sibling.
    canvas.junction_ban.add((0, 0, 0))
    nets = [
        domain._Net(
            source,
            destination,
            "gear",
            net_id=NetId(0, index + 1, "gear", NetRole.INTERNAL, index),
        )
        for index, destination in enumerate(destinations)
    ]
    make_grid = domain._make_grid
    overhead_path = domain.overhead_path
    workspaces: list[tuple[domain._Canvas, domain._Grid]] = []
    leaked_guards: set[Cell] = set()

    def observe_grid(*args, **kwargs):
        grid = make_grid(*args, **kwargs)
        workspaces.append((args[0], grid))
        return grid

    def observe_search(*args, **kwargs):
        path = overhead_path(*args, **kwargs)
        working_canvas, grid = workspaces[0]
        leaked_guards.update(cell for cell in working_canvas.guard if grid.occ[grid.index(cell)])
        return path

    monkeypatch.setattr(domain, "_make_grid", observe_grid)
    monkeypatch.setattr(domain, "overhead_path", observe_search)
    result = domain._route_all(
        canvas,
        nets,
        2001,
        35,
        bounds,
        budget={"left": 10_000},
        flow_limits=domain.RoutingFlowLimits((Fraction(1),) * len(nets), Fraction(6)),
    )
    assert not leaked_guards
    assert result.status is DetailedRouteStatus.ROUTED
    reached: set[int] = set()
    pending = [source.belt]
    while pending:
        index = pending.pop()
        if index in reached:
            continue
        reached.add(index)
        output = canvas.buildings[index].output_obj
        if output is not None:
            pending.append(output)
        pending.extend(canvas.buildings.by_input_obj(index))
    assert {destination.belt for destination in destinations} <= reached


@pytest.mark.parametrize("refuse_completion", (False, True))
def test_cluster_provider_hands_its_new_tap_to_the_dropped_sibling(
    monkeypatch: pytest.MonkeyPatch, refuse_completion: bool
) -> None:
    from flab2bp.layout.route_feedback import RouteFailureKind, RouteSettlementRefused

    bounds = (-4, -4, 16, 10)
    canvas = domain._Canvas(limit=bounds)

    def port(x: int, y: int) -> domain._Port:
        index = canvas.add(PlacedBuilding(2001, 35, x, y, carries_item="gear"))
        return domain._Port(index, x, y, x, x)

    source = port(0, 0)
    canvas.add(PlacedBuilding(2001, 35, -1, 0, carries_item="gear", output_obj=source.belt))
    destinations = (port(12, 0), port(1, 6))
    canvas.junction_ban.add((0, 0, 0))
    nets = [
        domain._Net(
            source,
            destination,
            "gear",
            net_id=NetId(0, index + 1, "gear", NetRole.INTERNAL, index),
        )
        for index, destination in enumerate(destinations)
    ]
    search = domain._astar
    initial_queries = 2

    def bounded_initial_queries(*args, **kwargs):
        nonlocal initial_queries
        if initial_queries:
            initial_queries -= 1
            kwargs["budget"]["left"] -= 1
            return domain._PathSearchResult(None, RouteFailureKind.BUDGET, (), 1)
        return search(*args, **kwargs)

    def refuse_candidate(_workspace, _owners):
        identity = nets[1].net_id
        assert identity is not None
        return RouteSettlementRefused("candidate refused", frozenset((identity,)))

    # Simulate bounded first-pass queries, not fabricated paths. The real
    # cluster search must preserve its blocked-root safeguard, then supply
    # the excluded sibling through the provider's newly established dock.
    monkeypatch.setattr(domain, "_astar", bounded_initial_queries)
    monkeypatch.setattr(domain, "_REPAIR_PASSES", 0)
    monkeypatch.setattr(domain, "RRR_MAX", 1)
    monkeypatch.setattr(domain, "_SINGLE_ROUND_NETS", 2)
    result = domain._route_all(
        canvas,
        nets,
        2001,
        35,
        bounds,
        budget={"left": 20_000},
        settle=refuse_candidate if refuse_completion else None,
    )
    reached: set[int] = set()
    pending = [source.belt]
    while pending:
        index = pending.pop()
        if index in reached:
            continue
        reached.add(index)
        output = canvas.buildings[index].output_obj
        if output is not None:
            pending.append(output)
        pending.extend(canvas.buildings.by_input_obj(index))
    assert destinations[0].belt in reached
    if refuse_completion:
        assert destinations[1].belt not in reached
        assert {failure.net_id for failure in result.failures} == {nets[1].net_id}
        assert {failure.kind for failure in result.failures} == {RouteFailureKind.COMMIT_LINK}
    else:
        assert result.status is DetailedRouteStatus.ROUTED
        assert destinations[1].belt in reached


@pytest.mark.parametrize("allow_displacement", (False, True))
def test_repair_moves_a_route_blocking_only_the_future_splitter(
    monkeypatch: pytest.MonkeyPatch, allow_displacement: bool
) -> None:
    from inspect import signature

    from flab2bp.layout import slots

    bounds = (-6, -6, 16, 8)
    canvas = domain._Canvas(
        limit=bounds, belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(0))
    )

    def port(x: int, y: int, item: str) -> domain._Port:
        index = canvas.add(PlacedBuilding(2001, 35, x, y, carries_item=item))
        return domain._Port(index, x, y, x, x)

    source = port(0, 0, "gear")
    canvas.add(PlacedBuilding(2001, 35, -1, 0, carries_item="gear", output_obj=source.belt))
    destinations = (port(12, 0, "gear"), port(1, 6, "gear"))
    foreign_source = port(-4, -1, "iron-ingot")
    foreign_destination = port(14, -1, "iron-ingot")
    canvas.junction_ban.update(
        (x, y, 0) for x in range(-6, 17) for y in range(-6, 9) if (x, y) != (1, 0)
    )
    canvas.guard.add((0, 1, 0))
    nets = [
        domain._Net(
            foreign_source,
            foreign_destination,
            "iron-ingot",
            net_id=NetId(0, 1, "iron-ingot", NetRole.INTERNAL, 0),
        ),
        *[
            domain._Net(
                source,
                destination,
                "gear",
                net_id=NetId(2, index + 3, "gear", NetRole.INTERNAL, index + 1),
            )
            for index, destination in enumerate(destinations)
        ],
    ]
    search = domain._astar
    search_signature = signature(search)

    def bounded_family_queries(*args, **kwargs):
        arguments = search_signature.bind(*args, **kwargs).arguments
        grid = arguments.get("grid")
        owners = arguments.get("blocking_owners", {})
        if (
            (1, 0, 0) in arguments["starts"]
            and owners.get((1, -1, 0)) == 0
            and grid is not None
            and not grid.occ[grid.index((1, -1, 0))]
        ):
            arguments["budget"] = {"left": 0}
            return search(**arguments)
        return search(*args, **kwargs)

    # The straight foreign route occupies (1, -1), not the family's belt
    # path along y=0, but it blocks the only permitted future splitter.
    # Bound only family queries that still treat that foreign body cell as
    # occupied. Repair's crossing view and every query after displacement
    # use the real search budget, independent of call order.
    monkeypatch.setattr(domain, "_astar", bounded_family_queries)
    monkeypatch.setattr(domain, "_SINGLE_ROUND_NETS", 3)
    monkeypatch.setattr(domain, "RRR_MAX", 1)
    monkeypatch.setattr(domain.last_mile, "B_MAX_STRANDED", 0)
    if not allow_displacement:
        monkeypatch.setattr(domain, "_REPAIR_MAX_VICTIMS", 0)
    result = domain._route_all(
        canvas,
        nets,
        2001,
        35,
        bounds,
        budget={"left": 100_000},
        prioritize_source_families=False,
        flow_limits=domain.RoutingFlowLimits((Fraction(6), Fraction(3), Fraction(3)), Fraction(6)),
    )
    networks: list[set[int]] = []
    for root, targets in ((foreign_source, (foreign_destination,)), (source, destinations)):
        reached: set[int] = set()
        pending = [root.belt]
        while pending:
            index = pending.pop()
            if index in reached:
                continue
            reached.add(index)
            output = canvas.buildings[index].output_obj
            if output is not None:
                pending.append(output)
            pending.extend(canvas.buildings.by_input_obj(index))
        networks.append(reached)
        item = canvas.buildings[root.belt].carries_item
        assert all(canvas.buildings[index].carries_item in (None, item) for index in reached)
        if root == foreign_source or allow_displacement:
            assert {target.belt for target in targets} <= reached
        else:
            assert not {target.belt for target in targets} & reached
    # The foreign full-capacity stream cannot subsidize either gear consumer,
    # nor can the two item families share a belt or a junction after repair.
    assert networks[0].isdisjoint(networks[1])
    if allow_displacement:
        assert result.status is DetailedRouteStatus.ROUTED
        assert any(
            building.item_id == catalog.SPLITTER_ID and (building.x, building.y) == (1, 0)
            for building in canvas.buildings
        )
    else:
        assert {failure.net_id for failure in result.failures} == {net.net_id for net in nets[1:]}
        assert any(
            building.carries_item == "iron-ingot" and (building.x, building.y) == (1, -1)
            for building in canvas.buildings
        )
    report = validate.validate(
        Placement(slots.assign_sorter_slots(tuple(canvas.buildings))),
        max_belt_z=Fraction(0),
        only={
            "geom.overlap",
            "geom.collide",
            "geom.belt_single_occupancy",
            "geom.altitude_range",
            "geom.altitude_step",
            "game.belt_crossing",
            "game.belt_collide",
            "belt.continuity",
            "belt.link_adjacent",
            "belt.port_dock",
            "belt.acyclic",
            "junction.stack_support",
            "junction.ports",
            "junction.colocated",
            "junction.port_pose",
            "junction.records_no_links",
        },
    )
    assert not report.errors


@pytest.mark.parametrize("allow_displacement", (False, True))
def test_repair_reselects_source_after_displacing_its_provider(
    monkeypatch: pytest.MonkeyPatch, allow_displacement: bool
) -> None:
    from flab2bp.layout.route_feedback import RouteFailureKind

    bounds = (-4, -4, 24, 8)
    canvas = domain._Canvas(
        limit=bounds, belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(0))
    )

    def port(x: int, y: int) -> domain._Port:
        index = canvas.add(PlacedBuilding(2001, 35, x, y, carries_item="gear"))
        return domain._Port(index, x, y, x, x)

    source = port(0, 0)
    canvas.add(PlacedBuilding(2001, 35, -1, 0, carries_item="gear", output_obj=source.belt))
    destinations = (port(20, 0), port(8, 4))
    canvas.guard.update(((0, -1, 0), (0, 1, 0)))
    nets = [
        domain._Net(
            source,
            destination,
            "gear",
            net_id=NetId(0, index + 1, "gear", NetRole.INTERNAL, index),
        )
        for index, destination in enumerate(destinations)
    ]
    search = domain._astar
    queries = 0

    def provider_crossing_query(*args, **kwargs):
        nonlocal queries
        queries += 1
        if queries == 2:
            kwargs["budget"]["left"] -= 1
            return domain._PathSearchResult(None, RouteFailureKind.BUDGET, (), 1)
        if queries == 3:
            start = next(cell for cell in args[1] if cell[1] == -1 and cell[0] < 16)
            path = (
                start,
                (start[0], -2, 0),
                (start[0], -3, 0),
                *((x, -3, 0) for x in range(start[0] + 1, 19)),
                *((18, y, 0) for y in range(-2, 4)),
                *((x, 3, 0) for x in range(17, 7, -1)),
            )
            assert path[-1] in args[2]
            kwargs["budget"]["left"] -= len(path)
            return domain._PathSearchResult(path, None, (), len(path))
        return search(*args, **kwargs)

    # A bounded primary query leaves a sibling behind. Its crossing witness
    # attaches to the provider it must displace, so that source must be reselected.
    monkeypatch.setattr(domain, "_astar", provider_crossing_query)
    monkeypatch.setattr(domain, "_SINGLE_ROUND_NETS", 2)
    monkeypatch.setattr(domain, "RRR_MAX", 1)
    monkeypatch.setattr(domain, "_REPAIR_PASSES", 1)
    monkeypatch.setattr(domain.last_mile, "B_MAX_STRANDED", 0)
    if not allow_displacement:
        monkeypatch.setattr(domain, "_REPAIR_MAX_VICTIMS", 0)
    result = domain._route_all(
        canvas, nets, 2001, 35, bounds, budget={"left": 100_000}, prioritize_source_families=False
    )
    reached: set[int] = set()
    pending = [source.belt]
    while pending:
        index = pending.pop()
        if index in reached:
            continue
        reached.add(index)
        output = canvas.buildings[index].output_obj
        if output is not None:
            pending.append(output)
        pending.extend(canvas.buildings.by_input_obj(index))
    assert destinations[0].belt in reached
    if allow_displacement:
        assert result.status is DetailedRouteStatus.ROUTED
        assert destinations[1].belt in reached
    else:
        assert destinations[1].belt not in reached
        assert {failure.net_id for failure in result.failures} == {nets[1].net_id}
