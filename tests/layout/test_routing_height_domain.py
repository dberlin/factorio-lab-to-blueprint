"""Save-specific height must survive occupancy, memoization and workspace copies."""

import math
from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog, colliders
from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.routing_domain import (
    _DEFAULT_BELT_RULES,
    _Canvas,
    _canvas_span,
    _crossing_ban_levels,
    _junction_ban_offsets,
    _junction_site_is_clear,
    _make_grid,
    _prepared_junction_ban,
    _PreparedRoutingProblem,
    _reserve_coater_belt_ban,
    _StagedStaticCache,
)


def _rules(max_z: Fraction, *, vertical: bool = True) -> catalog.BeltAltitudeRules:
    return replace(_DEFAULT_BELT_RULES, max_z=max_z, vertical_construction=vertical)


def test_high_plane_occupancy_is_not_lost_when_flattened() -> None:
    canvas = _Canvas(belt_rules=_rules(Fraction(17, 2)), limit=(0, 0, 2, 2))
    canvas.add(PlacedBuilding(2001, 35, 1, 1, z=Fraction(7)))
    canvas.guard.add((0, 1, 8))
    canvas.belt_ban[2, 1] = {6}
    assert canvas.limit is not None
    grid = _make_grid(canvas, canvas.limit, _canvas_span(canvas, canvas.limit), {(1, 2, 8): 3.0})

    for cell in ((1, 1, 7), (0, 1, 8), (2, 1, 6)):
        assert not canvas.free(cell)
        assert grid.occ[grid.index(cell)] == 0
    assert canvas.free((1, 1, 8))
    assert grid.occ[grid.index((1, 1, 8))] == 1
    assert grid.hist is not None
    assert grid.hist[grid.index((1, 2, 8))] == 3.0


@pytest.mark.parametrize(
    ("ceiling", "top"),
    ((Fraction(499, 100), 4), (Fraction(5), 5), (Fraction(501, 100), 5)),
)
def test_exact_ceiling_rejects_out_of_domain_cells_before_indexing(
    ceiling: Fraction, top: int
) -> None:
    canvas = _Canvas(belt_rules=_rules(ceiling), limit=(0, 0, 1, 1))
    assert canvas.limit is not None
    grid = _make_grid(canvas, canvas.limit, _canvas_span(canvas, canvas.limit), {})

    assert canvas.free((0, 0, top))
    assert canvas.free_world(0, 0, ceiling)
    assert not canvas.free_world(0, 0, ceiling + Fraction(1, 1000))
    for level in (-1, top + 1):
        assert not canvas.free((0, 0, level))
        with pytest.raises(IndexError):
            grid.index((0, 0, level))
    assert grid.occ[grid.index((0, 1, 0))] == 1


def test_crossing_geometry_retains_levels_above_old_lattice() -> None:
    machine = catalog.building(2303)
    obstacle = PlacedBuilding(
        machine.item_id,
        machine.model_index,
        0,
        0,
        z=Fraction(7),
        width=machine.width,
        height=machine.height,
    )
    assert 7 in _crossing_ban_levels(obstacle)
    canvas = _Canvas(belt_rules=_rules(Fraction(12)))
    canvas.add(obstacle, solid=True)
    assert not canvas.free((0, 0, 7))


def test_crossing_grid_rejects_projected_chemical_plant_corner() -> None:
    machine = catalog.building(2317)
    obstacle = PlacedBuilding(
        machine.item_id,
        machine.model_index,
        0,
        0,
        width=machine.width,
        height=machine.height,
    )
    canvas = _Canvas(belt_rules=_rules(Fraction(8)), limit=(-2, -2, 8, 6))
    canvas.add(obstacle, solid=True)
    assert canvas.limit is not None
    grid = _make_grid(canvas, canvas.limit, _canvas_span(canvas, canvas.limit), {})
    placed = colliders.Placed(machine.model_index, 0.0, 0.0, 0.0, 0.0)
    boxes = colliders.target_boxes(placed, *colliders.preview_pose(0.0, 0.0, 0.0, 0.0))

    for level, expected_collision in ((5, True), (6, False)):
        position, _ = colliders.preview_pose(-3.0, -1.0, level, 0.0)
        scale = 1 + colliders.BELT_PROBE_LIFT / math.hypot(*position)
        probe = (position[0] * scale, position[1] * scale, position[2] * scale)
        collision = any(
            colliders.sphere_box_overlap(probe, colliders.BELT_PROBE_RADIUS, box) for box in boxes
        )
        assert collision is expected_collision
        cell = (0, 1, level)
        assert canvas.free(cell) is not collision
        assert bool(grid.occ[grid.index(cell)]) is not collision


def test_obstacle_cache_keeps_independent_save_domains() -> None:
    machine = catalog.building(2303)
    obstacle = PlacedBuilding(
        machine.item_id,
        machine.model_index,
        0,
        0,
        width=machine.width,
        height=machine.height,
    )
    cache = _StagedStaticCache()
    low_rules, high_rules = _rules(Fraction(3)), _rules(Fraction(8))
    low = _prepared_junction_ban((obstacle,), (), belt_rules=low_rules, cache=cache)
    high = _prepared_junction_ban((obstacle,), (), belt_rules=high_rules, cache=cache)

    assert any(level >= 4 for _x, _y, level in high)
    assert low == frozenset(cell for cell in high if cell[2] < 4)
    assert _prepared_junction_ban((obstacle,), (), belt_rules=low_rules, cache=cache) == low


def test_elevated_coater_bans_its_actual_crossing_plane() -> None:
    canvas = _Canvas(belt_rules=_rules(Fraction(10)))
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    body = PlacedBuilding(
        coater.item_id,
        coater.model_index,
        0,
        0,
        z=Fraction(7),
        width=1,
        height=1,
        yaw=90.0,
    )
    _reserve_coater_belt_ban(canvas, body, catalog.building(2001).model_index)

    assert not canvas.free((0, 0, 8))
    assert canvas.free((0, 0, 1))


def test_workspace_and_clone_preserve_height_without_sharing_occupancy() -> None:
    rules = _rules(Fraction(17, 2), vertical=False)
    problem = _PreparedRoutingProblem(
        building_templates=(),
        blocked=(((1, 1, 7), 0),),
        solid=frozenset(),
        reserved=(),
        port_corridors=(),
        keep_out=frozenset(),
        guard=frozenset(),
        nets=(),
        core=(0, 0, 2, 2),
        route_bounds=(0, 0, 2, 2),
        limit=(0, 0, 2, 2),
        power_sites=(),
        sorters=0,
        coaters=0,
        direct_inserts=0,
        belt_rules=rules,
    )
    original = problem.new_workspace().canvas
    cloned = original.clone()
    independent = problem.new_workspace().canvas
    cloned.blocked[1, 1, 8] = 1

    assert not cloned.free((1, 1, 8))
    for canvas in (original, independent):
        assert not canvas.free((1, 1, 7))
        assert canvas.free((1, 1, 8))
        assert not canvas.free((1, 1, 9))
        assert canvas.ramped
    assert cloned.belt_rules == rules
    with pytest.raises(AttributeError):
        cloned.ramped = False  # type: ignore[misc]


def test_source_splitter_stack_unlock_is_independent_of_belt_height() -> None:
    rules = replace(_DEFAULT_BELT_RULES, max_z=Fraction(8), storage_level=2)
    canvas = _Canvas(belt_rules=rules)
    assert canvas.free((0, 0, 4))
    assert canvas.junction_is_clear(0, 0, 2)
    assert not canvas.junction_is_clear(0, 0, 4)
    assert not canvas.junction_is_clear(0, 0, 5)
    upgraded = _Canvas(belt_rules=replace(rules, storage_level=3))
    assert upgraded.junction_is_clear(0, 0, 4)
    assert upgraded.junction_is_clear(0, 0, 5)


@pytest.mark.parametrize("obstacle_z", (0, 3, 7))
def test_prepared_stack_bans_match_complete_physical_stacks(obstacle_z: int) -> None:
    machine = catalog.building(2303)
    obstacle = PlacedBuilding(
        machine.item_id,
        machine.model_index,
        0,
        0,
        z=Fraction(obstacle_z),
        width=machine.width,
        height=machine.height,
    )
    banned = _junction_ban_offsets(
        obstacle.item_id,
        obstacle.model_index,
        obstacle.width,
        obstacle.height,
        obstacle.yaw,
        obstacle.z,
        9,
    )
    for x, y in ((0, 0), (1, 1), (0, 2), (2, 0), (3, 3)):
        for level in range(9):
            assert ((x, y, level) not in banned) == _junction_site_is_clear(
                (obstacle,), x, y, level
            )
