from __future__ import annotations

from array import array
from dataclasses import replace
from fractions import Fraction
from heapq import heappop, heappush

import pytest

from tests.layout.test_route_kernel import _require_both_backends

type Transition = tuple[int, int, int, int, float]
type Transitions = tuple[tuple[Transition, ...], ...]
type Result = tuple[array[int] | None, int, int, array[int], int]


def _search(
    transitions: Transitions,
    flags: bytearray,
    start: int,
    goal: int,
    *,
    gh: int = 1,
    levels: int = 6,
    extra_edges: dict[int, tuple[tuple[int, float], ...]] | None = None,
    height_targets: tuple[int, ...] = (),
    height_costs: tuple[float, ...] = (),
    height_stride: int = 0,
) -> Result:
    _require_both_backends()
    from flab2bp.layout._route_kernel import astar_flat

    goal_flags = bytearray(len(flags))
    goal_flags[goal] = 1
    gx, gy = divmod(goal // levels, gh)
    return astar_flat(
        flags,
        array("d"),
        0.0,
        array("q"),
        0,
        goal_flags,
        array("q", (gx, gy)),
        True,
        (gx, gy, gx, gy),
        array("q", (start,)),
        gh,
        gh * levels,
        levels,
        array("d", [0.0] * levels),
        1000,
        2000,
        100,
        None,
        lambda _deadline: False,
        transitions,
        {} if extra_edges is None else extra_edges,
        array("q", height_targets),
        array("d", height_costs),
        height_stride,
    )


@pytest.mark.parametrize("levels", [6, 27])
def test_native_zero_run_climbs_cross_original_four_plane_ceiling(levels: int) -> None:
    transitions: Transitions = tuple(
        ((1, 0, 0, 0, 1.0),) if level + 1 < levels else () for level in range(levels)
    )
    # The admitted start can be unavailable in the occupancy mask. A zero via
    # offset must not turn that start into an intermediate occupancy requirement.
    result = _search(transitions, bytearray([0] + [1] * (levels - 1)), 0, levels - 1, levels=levels)
    assert result == (array("q", range(levels)), levels, 0, array("q"), 2000 - levels)


def test_native_uses_supplied_graph_without_implicit_flat_moves() -> None:
    result = _search(((),) * 6, bytearray([1] * 12), 0, 6)
    assert result == (None, 1, 2, array("q", (0,)), 1999)


@pytest.mark.parametrize(
    ("targets", "costs", "stride"),
    [
        ((0, 0, 0, 0, 0), (0.0,) * 12, 1),
        ((0, 0, 0, 0, 12), (0.0,) * 12, 2),
        ((0, 0, 2, 0, 0), (0.0,) * 12, 2),
        ((0, 0, 0, 0, 0), (0.0,) * 11, 2),
    ],
    ids=["short-distance-domain", "past-end-field", "outside-rectangle", "truncated-field"],
)
def test_native_rejects_height_tables_that_could_read_outside_buffers(
    targets: tuple[int, ...], costs: tuple[float, ...], stride: int
) -> None:
    with pytest.raises(ValueError):
        _search(
            ((),) * 6,
            bytearray([1] * 12),
            0,
            6,
            height_targets=targets,
            height_costs=costs,
            height_stride=stride,
        )


@pytest.mark.parametrize("blocked_via", [False, True])
def test_native_preserves_exact_ramp_via_and_direct_vertical_parents(blocked_via: bool) -> None:
    transitions: Transitions = (
        ((13, 6, 2, 0, 3.0),),
        ((1, 0, 0, 0, 1.0),),
        (),
        (),
        (),
        (),
    )
    flags = bytearray([1] * 18)
    flags[6] = not blocked_via
    result = _search(transitions, flags, 0, 14)
    expected: Result = (
        (None, 1, 2, array("q", (0,)), 1999)
        if blocked_via
        else (array("q", (0, 6, 13, 14)), 3, 0, array("q"), 1997)
    )
    assert result == expected


def test_native_rejects_y_wrap_without_padded_border() -> None:
    transitions: Transitions = (((6, 0, 0, 1, 1.0),), (), (), (), (), ())
    result = _search(transitions, bytearray([1] * 24), 6, 12, gh=2)
    assert result == (None, 1, 2, array("q", (6,)), 1999)


def test_native_skips_out_of_bounds_via_without_reading_it() -> None:
    transitions: Transitions = (((1, -(1 << 62), 0, 0, 1.0),), (), (), (), (), ())
    result = _search(transitions, bytearray([1] * 6), 0, 1)
    assert result == (None, 1, 2, array("q", (0,)), 1999)


@pytest.mark.parametrize(
    "transition",
    [
        (-1, 0, 0, 0, 1.0),  # below the source level domain
        (6, 0, 0, 0, 1.0),  # above the domain, not a horizontal move
        (1, 0, 0, 0, -1.0),
        (1, 0, 0, 0, float("nan")),
        (1, 0, 0, 0, float("inf")),
    ],
)
def test_native_rejects_invalid_transition_geometry_and_cost(transition: Transition) -> None:
    with pytest.raises(ValueError):
        _search(((transition,), (), (), (), (), ()), bytearray([1] * 6), 0, 1)


def test_native_requires_one_transition_group_per_level() -> None:
    with pytest.raises(ValueError):
        _search(((),), bytearray([1] * 6), 0, 1)


def test_native_table_search_matches_python_on_competing_vertical_and_ramp_routes() -> None:
    levels, gh, width = 6, 3, 5
    transitions: Transitions = tuple(
        tuple(
            [
                (dx * gh * levels + dy * levels, 0, dx, dy, 1.0 + level / 4)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            ]
            + (
                [(1, 0, 0, 0, 1.5), (2 * gh * levels + 1, gh * levels, 2, 0, 3.0)]
                if level + 1 < levels
                else []
            )
            + ([(-1, 0, 0, 0, 1.5)] if level else [])
        )
        for level in range(levels)
    )
    flags = bytearray([1] * (width * gh * levels))
    for y in range(gh):
        for level in range(5):
            flags[(2 * gh + y) * levels + level] = 0
    start, goal = levels, (4 * gh + 1) * levels
    best = {start: 0.0}
    parents: dict[int, tuple[int, int]] = {}
    queue = [(4.0, 0.0, start)]
    expansions = 0
    while queue:
        _, cost, node = heappop(queue)
        if cost > best[node]:
            continue
        expansions += 1
        if node == goal:
            break
        x, y = divmod(node // levels, gh)
        for offset, via, dx, dy, toll in transitions[node % levels]:
            if not (0 <= x + dx < width and 0 <= y + dy < gh):
                continue
            nxt = node + offset
            if not flags[nxt] or (via and not flags[node + via]):
                continue
            candidate = cost + toll
            if candidate < best.get(nxt, float("inf")):
                best[nxt] = candidate
                parents[nxt] = node, node + via if via else -1
                heuristic = abs(x + dx - 4) + abs(y + dy - 1)
                heappush(queue, (candidate + heuristic, candidate, nxt))
    assert goal in best
    path = array("q", (goal,))
    node = goal
    while node != start:
        node, via = parents[node]
        if via != -1:
            path.append(via)
        path.append(node)
    path.reverse()
    assert _search(transitions, flags, start, goal, gh=gh) == (
        path,
        expansions,
        0,
        array("q"),
        2000 - expansions,
    )


def test_native_sparse_connector_competes_with_vertical_moves_in_same_search() -> None:
    transitions: Transitions = tuple(
        ((1, 0, 0, 0, 1.0),) if level < 5 else () for level in range(6)
    )
    # The expensive early jump must lose to climbing to the cheaper connector.
    result = _search(
        transitions,
        bytearray([1] * 12),
        0,
        11,
        extra_edges={0: ((11, 10.0),), 2: ((11, 1.0),)},
    )
    assert result == (array("q", (0, 1, 2, 11)), 4, 0, array("q"), 1996)


def test_native_sparse_connector_does_not_invent_intermediate_belt_cells() -> None:
    flags = bytearray(18)
    flags[0] = flags[17] = 1
    result = _search(((),) * 6, flags, 0, 17, extra_edges={0: ((17, 4.0),)})
    assert result == (array("q", (0, 17)), 2, 0, array("q"), 1998)


def test_native_sparse_connector_requires_available_landing() -> None:
    result = _search(((),) * 6, bytearray((1, 0, 0, 0, 0, 0)), 0, 5, extra_edges={0: ((5, 1.0),)})
    assert result == (None, 1, 2, array("q", (0,)), 1999)


@pytest.mark.parametrize(
    "extra_edges",
    [
        {-1: ((1, 1.0),)},
        {6: ((1, 1.0),)},
        {0: ((-1, 1.0),)},
        {0: ((6, 1.0),)},
        {0: ((1, -1.0),)},
        {0: ((1, float("nan")),)},
        {0: ((1, float("inf")),)},
    ],
)
def test_native_rejects_unsafe_sparse_connector_edges(
    extra_edges: dict[int, tuple[tuple[int, float], ...]],
) -> None:
    with pytest.raises(ValueError):
        _search(((),) * 6, bytearray([1] * 6), 0, 1, extra_edges=extra_edges)


def test_native_relaxed_search_matches_python_across_27_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout import global_router, route_kernel, routing_domain
    from flab2bp.layout.route_feedback import FeedbackState, NetId, NetRole

    _require_both_backends()
    compiled = route_kernel._compiled_relaxed
    assert compiled is not None
    canvas = routing_domain._Canvas(
        belt_rules=replace(
            routing_domain._DEFAULT_BELT_RULES,
            max_z=Fraction(26),
            vertical_construction=True,
        )
    )
    grid = routing_domain._make_grid(canvas, (0, 0, 1, 0), (-2, -2, 3, 2), {})
    levels = grid.levels
    assert levels == 27
    movement: Transitions = tuple(
        tuple(
            [(grid.xstep, 0, 1, 0, 2.0)]
            + ([(1, 0, 0, 0, 1.0)] if level + 1 < levels else [])
            + ([(2, 0, 0, 0, 3.0)] if level + 2 < levels else [])
        )
        for level in range(levels)
    )
    flags = bytearray(grid.size)
    for level in range(levels):
        flags[grid.index((0, 0, level))] = 1
    start, goal = grid.index((0, 0, 0)), grid.index((1, 0, 26))
    flags[goal] = 1
    history = array("d", [0.0]) * grid.size
    history[grid.index((0, 0, 17))] = 2.0
    grid.hist = history
    net_id = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
    native_calls = 0

    def counting_kernel(*args: object) -> object:
        nonlocal native_calls
        native_calls += 1
        return compiled(*args)

    results = []
    for backend in (counting_kernel, None):
        monkeypatch.setattr(route_kernel, "_compiled_relaxed", backend)
        results.append(
            global_router._search_relaxed(
                grid,
                flags,
                (start,),
                (goal,),
                global_router._CapacityLedger(grid.size),
                frozenset(),
                FeedbackState((2, 1), {}, {}),
                net_id,
                100,
                None,
                movement=movement,
            )
        )
    assert native_calls == 1
    assert results[0] == results[1]
    # The cheaper path skips the congested level 17, then reads the highest
    # level's transition group to reach the adjacent column.
    expected = tuple((0, 0, level) for level in range(27) if level != 17) + ((1, 0, 26),)
    for result in results:
        assert result.path == expected
        path_indices = tuple(grid.index(cell) for cell in result.path)
        cost = sum(
            next(
                base
                for offset, _via, _dx, _dy, base in movement[source % levels]
                if source + offset == target
            )
            + history[target]
            for source, target in zip(path_indices, path_indices[1:], strict=False)
        )
        assert cost == 29.0


@pytest.mark.parametrize("last_count", [-1, 1, (1 << 63) - 1])
def test_native_relaxed_search_rejects_invalid_high_level_table_count(last_count: int) -> None:
    _require_both_backends()
    from flab2bp.layout._route_kernel import relaxed_search_flat

    targets = array("q", [0] * 26 + [last_count])
    with pytest.raises(ValueError):
        relaxed_search_flat(
            bytearray([1] * 27),
            array("d", [0.0] * 27),
            array("d"),
            1.0,
            targets,
            array("q", [0] * 27),
            array("d", [0.0] * 27),
            array("q", (0,)),
            array("q", (26,)),
            array("q", (0, 0)),
            1,
            27,
            100,
            None,
        )


@pytest.mark.parametrize(
    ("target_offset", "via_offset"),
    [
        ((1 << 63) - 1, 0),
        (-(1 << 63), 0),
        (-1, (1 << 63) - 1),
        (-1, -(1 << 63)),
    ],
)
def test_native_relaxed_search_skips_out_of_bounds_offsets_at_high_level(
    target_offset: int,
    via_offset: int,
) -> None:
    _require_both_backends()
    from flab2bp.layout._route_kernel import relaxed_search_flat

    result = relaxed_search_flat(
        bytearray([1] * 27),
        array("d", [0.0] * 27),
        array("d"),
        1.0,
        array("q", [0] * 26 + [1, target_offset]),
        array("q", [0] * 27 + [via_offset]),
        array("d", [0.0] * 27 + [1.0]),
        array("q", (26,)),
        array("q", (0,)),
        array("q", (0, 0)),
        1,
        27,
        100,
        None,
    )
    assert result == (None, 1, False, False)
