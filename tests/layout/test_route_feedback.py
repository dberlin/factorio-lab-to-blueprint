from typing import cast

import pytest

from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
    decay_feedback,
    feedback_cost_context,
    update_feedback,
)
from flab2bp.layout.sequence_pair import (
    DecodedPlacement,
    GapProfile,
    PlacementProblem,
    SequencePair,
    decode_sequence_pair,
)


def test_net_identity_distinguishes_roles_and_ordinals() -> None:
    internal = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    external = NetId(None, 7, "iron-ingot", NetRole.EXTERNAL, 0)
    same_position_external = NetId(2, 7, "iron-ingot", NetRole.EXTERNAL, 0)
    sibling = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 1)
    assert len({internal, external, same_position_external, sibling}) == 4


def test_detailed_result_counts_real_failures() -> None:
    net = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    failure = NetFailure(
        net_id=net,
        kind=RouteFailureKind.SEALED_POCKET,
        wall=((4, 5, 0),),
        blocking_nets=(),
        expansions=41,
    )
    result = DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(failure,),
        iterations=2,
        expansions=41,
    )
    assert result.failed_count == 1
    assert result.stranded == (net,)


def _detailed_failure(
    kind: RouteFailureKind,
    *,
    net: NetId | None = None,
    wall: tuple[tuple[int, int, int], ...] = ((4, 5, 0),),
) -> DetailedRouteResult:
    failed_net = net or NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    return DetailedRouteResult(
        status=(
            DetailedRouteStatus.BUDGET
            if kind is RouteFailureKind.BUDGET
            else DetailedRouteStatus.STRANDED
        ),
        routed=(),
        failures=(NetFailure(failed_net, kind, wall, (), 41),),
        iterations=2,
        expansions=41,
    )


@pytest.mark.parametrize(
    "kind",
    (
        RouteFailureKind.DYNAMIC_ACCESS,
        RouteFailureKind.SEALED_POCKET,
        RouteFailureKind.CONGESTION_WALL,
        RouteFailureKind.COMMIT_LINK,
    ),
)
def test_genuine_geometric_failure_bumps_net_and_wall(
    kind: RouteFailureKind,
) -> None:
    state = FeedbackState.empty(outline=(80, 120))
    failed = _detailed_failure(kind)

    updated = update_feedback(state, failed)

    assert updated.net_weight[failed.failures[0].net_id] == 1.0
    assert updated.cell_history[(4, 5, 0)] == 1.0
    assert state.net_weight == {}
    assert state.cell_history == {}


@pytest.mark.parametrize("kind", (RouteFailureKind.BUDGET, RouteFailureKind.STATIC_ACCESS))
def test_non_geometric_failure_is_an_exact_feedback_no_op(
    kind: RouteFailureKind,
) -> None:
    state = FeedbackState(
        outline=(80, 120),
        net_weight={NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0): 2.0},
        cell_history={(4, 5, 0): 3.0},
    )

    assert update_feedback(state, _detailed_failure(kind)) is state


def test_feedback_state_copies_and_freezes_input_mappings() -> None:
    net = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    weights = {net: 2.0}
    cells = {(4, 5, 0): 3.0}
    state = FeedbackState((80, 120), weights, cells)

    weights[net] = 7.0
    cells[(4, 5, 0)] = 9.0

    assert state.net_weight[net] == 2.0
    assert state.cell_history[(4, 5, 0)] == 3.0
    with pytest.raises(TypeError):
        cast(dict[NetId, float], state.net_weight)[net] = 4.0
    with pytest.raises(TypeError):
        cast(dict[tuple[int, int, int], float], state.cell_history)[(4, 5, 0)] = 4.0


def test_feedback_is_bounded_decayed_and_pruned_at_stage_boundary() -> None:
    net = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    state = FeedbackState.empty(outline=(80, 120))
    failed = _detailed_failure(RouteFailureKind.SEALED_POCKET, net=net)
    for _ in range(10):
        state = update_feedback(state, failed)

    assert state.net_weight[net] == 8.0
    assert state.cell_history[(4, 5, 0)] == 10.0

    decayed = decay_feedback(
        FeedbackState(
            outline=state.outline,
            net_weight={**state.net_weight, NetId(0, 1, "copper", NetRole.INTERNAL, 0): 1e-7},
            cell_history={**state.cell_history, (1, 1, 0): 1e-7},
        )
    )
    assert decayed.net_weight == {net: 6.8}
    assert decayed.cell_history == {(4, 5, 0): 8.5}


def test_cell_history_resets_and_net_weights_survive_outline_change() -> None:
    net = NetId(2, 7, "iron-ingot", NetRole.INTERNAL, 0)
    state = FeedbackState(
        outline=(80, 120),
        net_weight={net: 2.0},
        cell_history={(4, 5, 0): 3.0},
    )

    changed = state.for_outline((80, 121))

    assert changed.net_weight == {net: 2.0}
    assert changed.cell_history == {}
    assert state.for_outline(state.outline) is state


def test_feedback_cost_context_matches_problem_dimensions_and_box_history() -> None:
    problem = PlacementProblem(
        sizes=((2, 2), (2, 2), (1, 1)),
        nets=((0, 1), (1, 2)),
        outline_height=4,
        area_lower_bound=5,
    )
    decoded = decode_sequence_pair(
        SequencePair((0, 1, 2), (0, 1, 2)),
        GapProfile.zero(3),
        problem.sizes,
        outline_height=problem.outline_height,
        outline_width=6,
    )
    weighted = NetId(0, 1, "iron-ingot", NetRole.INTERNAL, 0)
    state = FeedbackState(
        outline=(6, 4),
        net_weight={weighted: 2.0},
        cell_history={(0, 0, 0): 1.0, (3, 1, 2): 2.0, (4, 0, 0): 4.0},
    )

    context = feedback_cost_context(state, problem, decoded)

    assert context.net_weights == (3.0, 1.0)
    assert context.history_cost_by_net == (3.0, 6.0)


def test_feedback_context_clips_fully_x_overflowed_net_box_to_zero() -> None:
    problem = PlacementProblem(((2, 2), (2, 2)), ((0, 1),), 4, 8)
    decoded = DecodedPlacement(
        x=(7, 9),
        y=(0, 0),
        width=11,
        used_height=2,
        x_windows=((7, 7), (9, 9)),
        y_windows=((0, 0), (0, 0)),
        gap_area=0,
    )
    state = FeedbackState((4, 4), {}, {(0, 0, 0): 3.0})

    context = feedback_cost_context(state, problem, decoded)

    assert context.history_cost_by_net == (0.0,)


def test_feedback_context_clips_fully_y_overflowed_net_box_to_zero() -> None:
    problem = PlacementProblem(((2, 2), (2, 2)), ((0, 1),), 4, 8)
    decoded = DecodedPlacement(
        x=(0, 0),
        y=(7, 9),
        width=2,
        used_height=11,
        x_windows=((0, 0), (0, 0)),
        y_windows=((7, 7), (9, 9)),
        gap_area=0,
    )
    state = FeedbackState((4, 4), {}, {(0, 0, 0): 3.0})

    context = feedback_cost_context(state, problem, decoded)

    assert context.history_cost_by_net == (0.0,)
