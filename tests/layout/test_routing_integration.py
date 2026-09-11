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
    from flab2bp.layout.geometric_router import overhead_path
    from flab2bp.layout.geometric_world import GeometricWorld

    canvas = domain._Canvas(belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(0)))
    world = GeometricWorld(canvas, history={(4, 0, 0): 40}, pressure=0.5)
    assert overhead_path(world, [(0, 0, 0)], {(4, 0, 0)}, (0, 0, 4, 0), None) == tuple(
        (x, 0, 0) for x in range(5)
    )
    canvas.guard.add((2, 0, 0))
    assert overhead_path(world, [(0, 0, 0)], {(4, 0, 0)}, (0, 0, 4, 0), None) is None


def test_overhead_dogleg_connects_when_both_corner_routes_are_blocked() -> None:
    from flab2bp.layout.geometric_router import overhead_path
    from flab2bp.layout.geometric_world import GeometricWorld

    canvas = domain._Canvas(belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(0)))
    canvas.guard.update({(3, 0, 0), (0, 3, 0)})
    path = overhead_path(GeometricWorld(canvas), [(0, 0, 0)], {(4, 4, 0)}, (0, 0, 4, 4), None)
    assert path is not None
    assert path[0] == (0, 0, 0) and path[-1] == (4, 4, 0)
    assert not canvas.guard.intersection(path)


def test_overhead_blocked_nearest_start_does_not_starve_clear_alternative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout import geometric_router
    from flab2bp.layout.geometric_world import GeometricWorld

    canvas = domain._Canvas(belt_rules=replace(domain._DEFAULT_BELT_RULES, max_z=Fraction(5)))
    canvas.guard.update((-1, y, z) for y in range(-4, 5) for z in range(canvas.levels))
    remaining = 256

    def bounded_work(_deadline: float | None) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining <= 0:
            raise geometric_router.Deadline

    # A deterministic query allowance: the unreachable nearest endpoint must
    # not consume every construction opportunity before the clear alternative.
    monkeypatch.setattr(geometric_router, "check_deadline", bounded_work)
    path = geometric_router.overhead_path(
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
    from flab2bp.layout import geometric_router
    from flab2bp.layout.geometric_world import GeometricWorld

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
            raise geometric_router.Deadline

    # Both starts are clear. The nearest start's ceiling rejects its ramp
    # approaches; the farther start can cross its ground wall overhead.
    monkeypatch.setattr(geometric_router, "check_deadline", bounded_work)
    path = geometric_router.overhead_path(
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
    from flab2bp.layout.geometric_router import overhead_path
    from flab2bp.layout.geometric_world import GeometricWorld

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
    from flab2bp.layout.geometric_router import overhead_path
    from flab2bp.layout.geometric_world import GeometricWorld

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
