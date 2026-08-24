import random
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from itertools import combinations, permutations
from typing import Any, cast

import pytest

from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
    select_lns_neighbourhood,
)
from flab2bp.layout.sequence_pair import (
    AnnealConfig,
    AnnealState,
    DecodedPlacement,
    GapProfile,
    MoveKind,
    PlacementCostContext,
    PlacementProblem,
    SearchEnergy,
    SequencePair,
    anneal_stage,
    apply_move,
    cheap_energy,
    decode_sequence_pair,
    derive_stage_seed,
    repair_neighbourhood,
)


def _boxes(
    decoded: DecodedPlacement, sizes: tuple[tuple[int, int], ...]
) -> tuple[tuple[int, int, int, int], ...]:
    return tuple(
        (decoded.x[index], decoded.y[index], decoded.x[index] + width, decoded.y[index] + height)
        for index, (width, height) in enumerate(sizes)
    )


def _assert_no_overlap(
    decoded: DecodedPlacement, sizes: tuple[tuple[int, int], ...]
) -> None:
    boxes = _boxes(decoded, sizes)
    for first, second in combinations(range(len(sizes)), 2):
        ax0, ay0, ax1, ay1 = boxes[first]
        bx0, by0, bx1, by1 = boxes[second]
        assert ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0


def test_sequence_pair_relations_decode_to_expected_axes() -> None:
    pair = SequencePair(positive=(0, 1, 2), negative=(0, 2, 1))
    decoded = decode_sequence_pair(
        pair, GapProfile.zero(3), ((3, 2), (4, 2), (2, 3)), outline_height=10
    )
    assert decoded.x[1] >= decoded.x[0] + 3
    assert decoded.y[1] >= decoded.y[2] + 3


def test_all_four_sequence_pair_relations_use_the_expected_direction() -> None:
    sizes = ((3, 2), (4, 5))
    expected: dict[
        tuple[tuple[int, int], tuple[int, int]], Callable[[DecodedPlacement], bool]
    ] = {
        ((0, 1), (0, 1)): lambda decoded: decoded.x[1] >= decoded.x[0] + 3,
        ((1, 0), (1, 0)): lambda decoded: decoded.x[0] >= decoded.x[1] + 4,
        ((0, 1), (1, 0)): lambda decoded: decoded.y[0] >= decoded.y[1] + 5,
        ((1, 0), (0, 1)): lambda decoded: decoded.y[1] >= decoded.y[0] + 2,
    }
    for (positive, negative), relation_holds in expected.items():
        decoded = decode_sequence_pair(
            SequencePair(positive, negative),
            GapProfile.zero(2),
            sizes,
            outline_height=7,
        )
        assert relation_holds(decoded)


def test_gap_profile_adds_explicit_channel_space() -> None:
    pair = SequencePair(positive=(0, 1), negative=(0, 1))
    plain = decode_sequence_pair(
        pair, GapProfile.zero(2), ((3, 2), (4, 2)), outline_height=6
    )
    gapped = decode_sequence_pair(
        pair,
        GapProfile(east=(2, 0), north=(0, 0)),
        ((3, 2), (4, 2)),
        outline_height=6,
    )
    assert gapped.x[1] == plain.x[1] + 2
    assert gapped.gap_area == 4


def test_north_gap_is_added_to_outgoing_vertical_constraints() -> None:
    pair = SequencePair(positive=(0, 1), negative=(1, 0))
    plain = decode_sequence_pair(
        pair, GapProfile.zero(2), ((3, 2), (4, 3)), outline_height=8
    )
    gapped = decode_sequence_pair(
        pair,
        GapProfile(east=(0, 0), north=(0, 2)),
        ((3, 2), (4, 3)),
        outline_height=8,
    )
    assert gapped.y[0] == plain.y[0] + 2
    assert gapped.gap_area == 8


def test_decoded_rectangles_never_overlap() -> None:
    sizes = ((3, 2), (4, 3), (2, 5), (1, 4))
    for positive in permutations(range(4)):
        for negative in permutations(range(4)):
            decoded = decode_sequence_pair(
                SequencePair(positive, negative),
                GapProfile.zero(4),
                sizes,
                outline_height=sum(height for _width, height in sizes),
            )
            _assert_no_overlap(decoded, sizes)


def test_coordinate_windows_use_forward_earliest_and_reverse_latest_paths() -> None:
    horizontal = decode_sequence_pair(
        SequencePair((0, 1), (0, 1)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=6,
        outline_width=10,
    )
    assert horizontal.x == (0, 3)
    assert horizontal.x_windows == ((0, 3), (3, 6))
    assert horizontal.y_windows == ((0, 4), (0, 4))

    vertical = decode_sequence_pair(
        SequencePair((0, 1), (1, 0)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=6,
    )
    assert vertical.y == (2, 0)
    assert vertical.y_windows == ((2, 4), (0, 2))


def test_latest_windows_propagate_through_a_three_rectangle_chain() -> None:
    decoded = decode_sequence_pair(
        SequencePair((0, 1, 2), (0, 1, 2)),
        GapProfile.zero(3),
        ((2, 1), (3, 1), (4, 1)),
        outline_height=2,
        outline_width=12,
    )
    assert decoded.x == (0, 2, 5)
    assert decoded.x_windows == ((0, 3), (2, 5), (5, 8))


def test_default_outline_width_is_the_compacted_width() -> None:
    decoded = decode_sequence_pair(
        SequencePair((0, 1), (0, 1)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=6,
    )
    assert decoded.width == 7
    assert decoded.x_windows == ((0, 0), (3, 3))


def test_outline_overflow_returns_infeasible_windows_for_scoring() -> None:
    decoded = decode_sequence_pair(
        SequencePair((0, 1), (1, 0)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=3,
    )
    assert decoded.used_height == 4
    assert decoded.y_windows == ((2, 1), (0, -1))


def test_generated_cases_are_deterministic_legal_and_integer_only() -> None:
    for size in range(1, 8):
        sizes = tuple((1 + index % 4, 1 + (index * 3) % 5) for index in range(size))
        identity = tuple(range(size))
        generated = {
            (
                identity[offset:] + identity[:offset],
                tuple(reversed(identity[:offset])) + tuple(reversed(identity[offset:])),
            )
            for offset in range(size)
        }
        generated.update(
            (positive, tuple(reversed(negative))) for positive, negative in tuple(generated)
        )
        gaps = GapProfile(
            east=tuple(index % 5 for index in range(size)),
            north=tuple((index * 2) % 5 for index in range(size)),
        )
        outline_height = sum(
            height + gaps.north[index]
            for index, (_width, height) in enumerate(sizes)
        )
        for positive, negative in sorted(generated):
            pair = SequencePair(positive, negative)
            first = decode_sequence_pair(pair, gaps, sizes, outline_height=outline_height)
            second = decode_sequence_pair(pair, gaps, sizes, outline_height=outline_height)
            assert first == second
            assert all(type(coordinate) is int for coordinate in first.x + first.y)
            _assert_no_overlap(first, sizes)


def test_sequence_pair_and_gap_profile_are_validated_and_immutable() -> None:
    pair = SequencePair((0, 1), (1, 0))
    gaps = GapProfile.zero(2)
    with pytest.raises(FrozenInstanceError):
        pair.positive = (1, 0)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        gaps.east = (1, 0)  # type: ignore[misc]

    for positive, negative in (
        ((0, 0), (0, 1)),
        ((0, 1), (0, 2)),
        ((0,), (0, 1)),
        ((0, "1"), (0, 1)),
    ):
        with pytest.raises(ValueError, match="every strip exactly once"):
            SequencePair(positive, negative)  # type: ignore[arg-type]

    for east, north in (((-1,), (0,)), ((5,), (0,)), ((0,), (0, 1)), ((1.0,), (0,))):
        with pytest.raises(ValueError, match="gap"):
            GapProfile(east, north)  # type: ignore[arg-type]


def test_decode_rejects_structurally_invalid_input() -> None:
    pair = SequencePair((0,), (0,))
    gaps = GapProfile.zero(1)
    floating_sizes = cast(tuple[tuple[int, int], ...], ((1.0, 1),))
    invalid_calls: tuple[Callable[[], DecodedPlacement], ...] = (
        lambda: decode_sequence_pair(pair, GapProfile.zero(2), ((1, 1),), outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, (), outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, ((0, 1),), outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, floating_sizes, outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, ((1, 1),), outline_height=0),
        lambda: decode_sequence_pair(pair, gaps, ((1, 1),), outline_height=1, outline_width=0),
    )
    for call in invalid_calls:
        with pytest.raises(ValueError):
            call()


def test_placement_problem_validates_geometry_nets_and_bounds() -> None:
    problem = PlacementProblem(
        sizes=((3, 2), (4, 3)),
        nets=((0, 1),),
        outline_height=5,
        area_lower_bound=18,
    )
    assert problem.size == 2
    with pytest.raises(FrozenInstanceError):
        problem.outline_height = 6  # type: ignore[misc]

    invalid_kwargs: tuple[dict[str, Any], ...] = (
        {"sizes": ((0, 2),), "nets": (), "outline_height": 2, "area_lower_bound": 0},
        {"sizes": ((1, 2),), "nets": ((0, 1),), "outline_height": 2, "area_lower_bound": 2},
        {"sizes": ((1, 2),), "nets": (), "outline_height": 0, "area_lower_bound": 2},
        {"sizes": ((1, 2),), "nets": (), "outline_height": 2, "area_lower_bound": -1},
    )
    for kwargs in invalid_kwargs:
        with pytest.raises(ValueError):
            PlacementProblem(**kwargs)


def _tiny_placement_problem() -> PlacementProblem:
    return PlacementProblem(
        sizes=((3, 2), (2, 4), (4, 1), (1, 3)),
        nets=((0, 1), (1, 2), (2, 3), (0, 3)),
        outline_height=6,
        area_lower_bound=20,
    )


def test_every_move_preserves_both_permutations_and_gap_bounds() -> None:
    state = AnnealState.initial(size=8, seed=41)
    for kind in MoveKind:
        moved = apply_move(state, kind, random.Random(7))
        moved.pair.validate(8)
        assert all(0 <= gap <= 4 for gap in moved.gaps.east + moved.gaps.north)


@pytest.mark.parametrize(
    ("kind", "positive_changes", "negative_changes", "gap_changes"),
    (
        (MoveKind.SWAP_POSITIVE, True, False, False),
        (MoveKind.SWAP_NEGATIVE, False, True, False),
        (MoveKind.SWAP_BOTH, True, True, False),
        (MoveKind.INSERT_POSITIVE, True, False, False),
        (MoveKind.INSERT_NEGATIVE, False, True, False),
        (MoveKind.GAP_STEP, False, False, True),
    ),
)
def test_each_move_kind_mutates_only_its_owned_state(
    kind: MoveKind,
    positive_changes: bool,
    negative_changes: bool,
    gap_changes: bool,
) -> None:
    state = AnnealState(
        pair=SequencePair(tuple(range(6)), tuple(range(6))),
        gaps=GapProfile.zero(6),
        base_seed=19,
        stage_index=3,
    )

    moved = apply_move(state, kind, random.Random(7))

    assert (moved.pair.positive != state.pair.positive) is positive_changes
    assert (moved.pair.negative != state.pair.negative) is negative_changes
    assert (moved.gaps != state.gaps) is gap_changes
    assert moved.base_seed == state.base_seed
    assert moved.stage_index == state.stage_index
    if kind is MoveKind.SWAP_BOTH:
        assert moved.pair.positive == moved.pair.negative


def test_gap_move_is_one_bounded_step_including_at_both_bounds() -> None:
    for initial_gap in (0, 2, 4):
        state = AnnealState(
            pair=SequencePair((0,), (0,)),
            gaps=GapProfile((initial_gap,), (initial_gap,)),
            base_seed=3,
            stage_index=0,
        )
        for seed in range(20):
            moved = apply_move(state, MoveKind.GAP_STEP, random.Random(seed))
            deltas = tuple(
                abs(after - before)
                for after, before in zip(
                    moved.gaps.east + moved.gaps.north,
                    state.gaps.east + state.gaps.north,
                    strict=True,
                )
            )
            assert sum(deltas) == 1
            assert all(0 <= gap <= 4 for gap in moved.gaps.east + moved.gaps.north)


def test_swap_both_swaps_the_same_strip_ids_in_each_permutation() -> None:
    state = AnnealState(
        pair=SequencePair((0, 1, 2, 3), (3, 1, 0, 2)),
        gaps=GapProfile.zero(4),
        base_seed=7,
    )

    moved = apply_move(state, MoveKind.SWAP_BOTH, random.Random(7))

    positive_strips = {
        before
        for before, after in zip(
            state.pair.positive, moved.pair.positive, strict=True
        )
        if before != after
    }
    negative_strips = {
        before
        for before, after in zip(
            state.pair.negative, moved.pair.negative, strict=True
        )
        if before != after
    }
    assert positive_strips == negative_strips


def test_moves_are_legal_no_ops_for_empty_and_singleton_states() -> None:
    for size in (0, 1):
        state = AnnealState.initial(size=size, seed=5)
        for kind in MoveKind:
            moved = apply_move(state, kind, random.Random(11))
            moved.pair.validate(size)
            assert len(moved.gaps.east) == size


def test_cheap_energy_uses_every_normalized_component() -> None:
    problem = PlacementProblem(
        sizes=((2, 3), (4, 1)),
        nets=((0, 1),),
        outline_height=5,
        area_lower_bound=10,
    )
    decoded = DecodedPlacement(
        x=(1, 4),
        y=(2, 6),
        width=7,
        used_height=8,
        x_windows=((1, 1), (4, 4)),
        y_windows=((2, 2), (6, 6)),
        gap_area=5,
    )
    context = PlacementCostContext(
        net_weights=(2.0,),
        history_cost_by_net=(3.0,),
        missed_direct_inserts=1,
    )

    energy = cheap_energy(problem, decoded, context)

    assert energy.hard_outline_overflow == 3
    assert energy.scalar == pytest.approx(
        3.5  # normalized width * outline height
        + 0.35 * 1.4  # feedback-weighted HPWL
        + 0.2 * 3.0  # history congestion
        + 0.1 * 1.0  # missed direct inserts
        + 0.05 * 0.5  # explicit gap area
    )


def test_cheap_energy_handles_zero_area_and_no_nets_without_zero_division() -> None:
    problem = PlacementProblem(
        sizes=(),
        nets=(),
        outline_height=5,
        area_lower_bound=0,
    )
    decoded = decode_sequence_pair(
        SequencePair((), ()),
        GapProfile.zero(0),
        (),
        outline_height=5,
    )

    assert cheap_energy(problem, decoded, PlacementCostContext((), ())) == SearchEnergy(0, 0.0)


def test_search_energy_orders_hard_outline_overflow_before_scalar() -> None:
    assert SearchEnergy(0, 1_000_000.0) < SearchEnergy(1, -1_000_000.0)


def test_cost_context_rejects_non_finite_or_negative_values() -> None:
    invalid_calls: tuple[Callable[[], PlacementCostContext], ...] = (
        lambda: PlacementCostContext((-1.0,), (0.0,)),
        lambda: PlacementCostContext((float("inf"),), (0.0,)),
        lambda: PlacementCostContext((1.0,), (float("nan"),)),
        lambda: PlacementCostContext((1.0,), (0.0,), missed_direct_inserts=-1),
    )
    for call in invalid_calls:
        with pytest.raises(ValueError):
            call()


def test_cost_context_must_match_problem_net_count() -> None:
    problem = PlacementProblem(((1, 1),), ((0, 0),), 1, 1)
    decoded = decode_sequence_pair(
        SequencePair((0,), (0,)),
        GapProfile.zero(1),
        problem.sizes,
        outline_height=1,
    )
    with pytest.raises(ValueError, match="net count"):
        cheap_energy(problem, decoded, PlacementCostContext((), ()))


def test_derived_stage_seeds_are_stable_and_stage_specific() -> None:
    assert derive_stage_seed(123, 4) == derive_stage_seed(123, 4)
    assert derive_stage_seed(123, 4) != derive_stage_seed(123, 5)
    assert derive_stage_seed(123, 4) != derive_stage_seed(124, 4)


def test_initial_states_are_seeded_reproducibly_for_multi_start() -> None:
    assert AnnealState.initial(12, 17) == AnnealState.initial(12, 17)
    assert AnnealState.initial(12, 17).pair != AnnealState.initial(12, 18).pair


def test_fixed_seed_reproduces_stage_incumbent_and_accepted_move_count() -> None:
    problem = _tiny_placement_problem()
    config = AnnealConfig.test()

    a = anneal_stage(problem, AnnealState.initial(problem.size, 17), config)
    b = anneal_stage(problem, AnnealState.initial(problem.size, 17), config)

    assert a.incumbent == b.incumbent
    assert a.accepted_moves == b.accepted_moves
    assert a.final_state == b.final_state
    assert a.elites == b.elites


def test_anneal_stage_advances_once_and_retains_ordered_distinct_elites() -> None:
    problem = _tiny_placement_problem()
    state = AnnealState.initial(problem.size, 29)
    config = AnnealConfig(
        moves_per_stage=80,
        initial_temperature=1.5,
        final_temperature=0.05,
        elite_count=5,
    )

    result = anneal_stage(problem, state, config)

    assert result.final_state.stage_index == state.stage_index + 1
    assert result.final_state.base_seed == state.base_seed
    assert 0 <= result.accepted_moves <= config.moves_per_stage
    assert 1 <= len(result.elites) <= config.elite_count
    assert len({elite.key for elite in result.elites}) == len(result.elites)
    assert result.elites == tuple(
        sorted(result.elites, key=lambda elite: (elite.energy, elite.key))
    )
    assert result.incumbent == result.elites[0]
    result.final_state.pair.validate(problem.size)
    assert all(
        0 <= gap <= 4
        for gap in result.final_state.gaps.east + result.final_state.gaps.north
    )


def test_anneal_config_rejects_invalid_schedule_values() -> None:
    invalid_kwargs: tuple[dict[str, Any], ...] = (
        {"moves_per_stage": 0},
        {"initial_temperature": 0.0},
        {"final_temperature": 0.0},
        {"initial_temperature": 0.5, "final_temperature": 1.0},
        {"elite_count": 0},
    )
    for kwargs in invalid_kwargs:
        with pytest.raises(ValueError):
            AnnealConfig(**kwargs)


def _lns_failure(
    net: NetId,
    *,
    kind: RouteFailureKind = RouteFailureKind.SEALED_POCKET,
    wall: tuple[tuple[int, int, int], ...] = (),
    blocking_nets: tuple[NetId, ...] = (),
) -> DetailedRouteResult:
    return DetailedRouteResult(
        status=(
            DetailedRouteStatus.BUDGET
            if kind is RouteFailureKind.BUDGET
            else DetailedRouteStatus.STRANDED
        ),
        routed=(),
        failures=(NetFailure(net, kind, wall, blocking_nets, 10),),
        iterations=1,
        expansions=10,
    )


def _lns_geometry(
    size: int,
    *,
    gaps: GapProfile | None = None,
) -> tuple[SequencePair, GapProfile, PlacementProblem, DecodedPlacement]:
    pair = SequencePair(tuple(range(size)), tuple(range(size)))
    profile = gaps or GapProfile.zero(size)
    problem = PlacementProblem(
        sizes=((2, 2),) * size,
        nets=(),
        outline_height=4,
        area_lower_bound=4 * size,
    )
    decoded = decode_sequence_pair(
        pair,
        profile,
        problem.sizes,
        outline_height=problem.outline_height,
    )
    return pair, profile, problem, decoded


def _locked_relative_order(
    pair: SequencePair, locked: frozenset[int]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    return (
        tuple(strip for strip in pair.positive if strip in locked),
        tuple(strip for strip in pair.negative if strip in locked),
    )


def test_lns_selects_stranded_blocking_endpoints_and_sequence_neighbours() -> None:
    pair, gaps, problem, decoded = _lns_geometry(10)
    stranded = NetId(3, 4, "iron", NetRole.INTERNAL, 0)
    blocker = NetId(7, 7, "copper", NetRole.INTERNAL, 0)

    neighbourhood = select_lns_neighbourhood(
        _lns_failure(stranded, blocking_nets=(blocker,)),
        pair,
        gaps,
        problem,
        decoded,
    )

    assert neighbourhood == frozenset({2, 3, 4, 5, 6, 7, 8})


def test_lns_selects_only_gap_strips_intersecting_failure_hot_boxes() -> None:
    gaps = GapProfile(
        east=(0, 2, 0),
        north=(0, 0, 0),
    )
    pair, gaps, problem, decoded = _lns_geometry(3, gaps=gaps)
    no_strip_net = NetId(None, None, "iron", NetRole.EXTERNAL, 0)

    neighbourhood = select_lns_neighbourhood(
        _lns_failure(no_strip_net, wall=((5, 1, 0),)),
        pair,
        gaps,
        problem,
        decoded,
    )

    assert neighbourhood == frozenset({1})


def test_budget_failure_creates_no_lns_neighbourhood() -> None:
    pair, gaps, problem, decoded = _lns_geometry(6)
    failure = _lns_failure(
        NetId(2, 3, "iron", NetRole.INTERNAL, 0),
        kind=RouteFailureKind.BUDGET,
        wall=((4, 1, 0),),
        blocking_nets=(NetId(4, 5, "copper", NetRole.INTERNAL, 0),),
    )

    assert (
        select_lns_neighbourhood(
            failure,
            pair,
            gaps,
            problem,
            decoded,
            stagnation=100,
            grow_after=2,
        )
        == frozenset()
    )


def test_lns_neighbourhood_grows_one_sequence_ring_after_stagnation() -> None:
    pair, gaps, problem, decoded = _lns_geometry(8)
    failure = _lns_failure(NetId(3, 3, "iron", NetRole.INTERNAL, 0))

    focused = select_lns_neighbourhood(
        failure, pair, gaps, problem, decoded, stagnation=0, grow_after=2
    )
    grown = select_lns_neighbourhood(
        failure, pair, gaps, problem, decoded, stagnation=2, grow_after=2
    )

    assert focused == frozenset({2, 3, 4})
    assert grown == frozenset({1, 2, 3, 4, 5})


def test_lns_repair_preserves_exact_locked_order_and_locked_gaps() -> None:
    pair = SequencePair(tuple(range(8)), tuple(range(8)))
    gaps = GapProfile(
        east=(0, 1, 2, 3, 4, 3, 2, 1),
        north=(1, 2, 3, 4, 3, 2, 1, 0),
    )
    neighbourhood = frozenset({3, 4})
    locked = frozenset({0, 1, 2, 5, 6, 7})

    repaired = repair_neighbourhood(
        pair, gaps, neighbourhood, seed=9, strip_weights={3: 5.0, 4: 1.0}
    )

    assert _locked_relative_order(repaired.pair, locked) == _locked_relative_order(
        pair, locked
    )
    assert tuple(repaired.gaps.east[index] for index in locked) == tuple(
        gaps.east[index] for index in locked
    )
    assert tuple(repaired.gaps.north[index] for index in locked) == tuple(
        gaps.north[index] for index in locked
    )
    assert all(0 <= gap <= 4 for gap in repaired.gaps.east + repaired.gaps.north)


def test_lns_repair_is_deterministic_for_seed_and_weights() -> None:
    pair = SequencePair(tuple(range(8)), tuple(reversed(range(8))))
    gaps = GapProfile.zero(8)
    neighbourhood = frozenset({2, 3, 4, 5})
    weights = {2: 1.0, 3: 2.0, 4: 4.0, 5: 8.0}

    first = repair_neighbourhood(
        pair, gaps, neighbourhood, seed=91, strip_weights=weights
    )
    second = repair_neighbourhood(
        pair, gaps, neighbourhood, seed=91, strip_weights=weights
    )

    assert first == second
    first.pair.validate(8)
    assert first != repair_neighbourhood(
        pair,
        gaps,
        neighbourhood,
        seed=91,
        strip_weights={2: 8.0, 3: 4.0, 4: 2.0, 5: 1.0},
    )
