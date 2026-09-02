from __future__ import annotations

import math

import pytest

from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
    select_lns_neighbourhood,
)
from flab2bp.layout.sequence_alns import (
    C_CONTEXT_FRACTION_STEPS,
    C_DUCB_DISCOUNT,
    C_MAX_DESTROY_STRIPS,
    C_MIN_DESTROY_STRIPS,
    REWARD_RANKS,
    SHIPPED_DESTROY,
    SHIPPED_REPAIR,
    DestroyOperator,
    OperatorChoice,
    OperatorContext,
    OperatorMetrics,
    OperatorOutcome,
    OperatorSession,
    RepairOperator,
    destroy_strips,
    metrics_from_evaluation,
    operator_scale,
    operator_tally,
    remaining_fraction_bucket,
    reward_vector,
)
from flab2bp.layout.sequence_pair import AnnealState, PlacementProblem, decode_state


def _context(**overrides: object) -> OperatorContext:
    base: dict[str, object] = {
        "strip_count": 20,
        "stagnation": 0,
        "remaining_fraction": 7,
    }
    base.update(overrides)
    return OperatorContext(**base)  # type: ignore[arg-type]


def _metrics(**overrides: object) -> OperatorMetrics:
    base: dict[str, object] = {
        "validator_clean": False,
        "failed_nets": 4,
        "band_overflow": 10,
        "congestion": 8.0,
        "area": 1000,
    }
    base.update(overrides)
    return OperatorMetrics(**base)  # type: ignore[arg-type]


def _choice(destroy: DestroyOperator, repair: RepairOperator) -> OperatorChoice:
    return OperatorChoice(destroy=destroy, repair=repair, scale=4, ordinal=0)


def _outcome(before: OperatorMetrics, after: OperatorMetrics) -> OperatorOutcome:
    return OperatorOutcome(
        choice=_choice(DestroyOperator.FAILED_ENDPOINTS, RepairOperator.SEQUENCE_REINSERT),
        before=before,
        after=after,
        applied=True,
    )


def _problem() -> PlacementProblem:
    return PlacementProblem(
        sizes=((4, 3), (4, 3), (4, 3), (4, 3)),
        nets=((0, 1), (1, 2), (2, 3)),
        outline_height=12,
        area_lower_bound=48,
    )


def _routing() -> DetailedRouteResult:
    return DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(
            NetFailure(
                net_id=NetId(0, 1, "iron-ore", NetRole.INTERNAL, 0),
                kind=RouteFailureKind.CONGESTION_WALL,
                wall=((2, 2, 0), (2, 3, 0)),
                blocking_nets=(NetId(2, 3, "copper-ore", NetRole.INTERNAL, 1),),
                expansions=17,
            ),
        ),
        iterations=1,
        expansions=17,
    )


# --- portfolio ---------------------------------------------------------------


def test_only_the_shipped_operators_are_ever_selected() -> None:
    session = OperatorSession()
    for _ in range(12):
        choice = session.select(_context())
        assert choice.destroy in SHIPPED_DESTROY
        assert choice.repair in SHIPPED_REPAIR
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)


def test_a_follow_up_destroy_operator_has_no_dispatch_branch() -> None:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    with pytest.raises(NotImplementedError):
        destroy_strips(
            DestroyOperator.BLOCKER_COMPONENT,
            scale=4,
            result=_routing(),
            pair=state.pair,
            gaps=state.gaps,
            problem=problem,
            decoded=decoded,
            band_target_width=decoded.width,
        )


# --- selector ----------------------------------------------------------------


def test_every_arm_is_played_once_before_any_arm_is_played_twice() -> None:
    session = OperatorSession()
    seen_destroy: list[DestroyOperator] = []
    seen_repair: list[RepairOperator] = []
    for _ in range(max(len(SHIPPED_DESTROY), len(SHIPPED_REPAIR))):
        choice = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
        seen_destroy.append(choice.destroy)
        seen_repair.append(choice.repair)
        session.observe(choice, (1.0, 0.0, 0.0, 0.0, 0.0), applied=True)
    assert seen_destroy[: len(SHIPPED_DESTROY)] == list(SHIPPED_DESTROY)
    assert seen_repair[: len(SHIPPED_REPAIR)] == list(SHIPPED_REPAIR)
    assert len(set(seen_destroy[: len(SHIPPED_DESTROY)])) == len(SHIPPED_DESTROY)


def test_a_tie_on_rank_zero_is_broken_by_rank_one() -> None:
    session = OperatorSession()
    rewards = {
        DestroyOperator.FAILED_ENDPOINTS: (0.0, 1.0, 0.0, 0.0, 0.0),
        DestroyOperator.BAND_BOUNDARY: (0.0, 5.0, 0.0, 0.0, 0.0),
    }
    for _ in range(len(SHIPPED_DESTROY)):
        choice = session.select(_context())
        session.observe(choice, rewards[choice.destroy], applied=True)
    assert session.select(_context()).destroy is DestroyOperator.BAND_BOUNDARY


def test_rank_zero_outranks_every_later_rank() -> None:
    session = OperatorSession()
    rewards = {
        DestroyOperator.FAILED_ENDPOINTS: (1.0, 0.0, 0.0, 0.0, 0.0),
        DestroyOperator.BAND_BOUNDARY: (0.0, 9.0, 9.0, 9.0, 9.0),
    }
    for _ in range(len(SHIPPED_DESTROY)):
        choice = session.select(_context())
        session.observe(choice, rewards[choice.destroy], applied=True)
    assert session.select(_context()).destroy is DestroyOperator.FAILED_ENDPOINTS


def test_the_exploration_bonus_only_breaks_a_tie_on_every_mean() -> None:
    session = OperatorSession()
    for _ in range(len(SHIPPED_DESTROY)):
        choice = session.select(_context())
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)
    # Both arms have identical (zero) means, so the less-played arm wins on the bonus.
    first = session.select(_context())
    session.observe(first, (0.0,) * REWARD_RANKS, applied=True)
    assert session.select(_context()).destroy is not first.destroy


def test_selection_is_deterministic_for_the_same_observation_sequence() -> None:
    def run() -> tuple[OperatorChoice, ...]:
        session = OperatorSession()
        rewards = [
            (0.0, 1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 2.0, 0.0, 0.0),
            (1.0, 0.0, 0.0, 0.0, 0.0),
        ]
        for index in range(24):
            choice = session.select(_context(stagnation=index % 3))
            session.observe(choice, rewards[index % 3], applied=True)
        return session.choices

    assert run() == run()


def test_discounting_decays_every_arm_on_every_observation() -> None:
    session = OperatorSession()
    played = session.select(_context())
    for _ in range(4):
        session.observe(played, (0.0,) * REWARD_RANKS, applied=True)
    expected = sum(C_DUCB_DISCOUNT**index for index in range(4))
    assert math.isclose(
        session.credit[f"count:{played.destroy.value}"], expected, rel_tol=1e-12
    )


def test_local_exact_pack_is_not_offered_without_room_for_a_window() -> None:
    session = OperatorSession()
    for _ in range(12):
        choice = session.select(_context(remaining_fraction=0))
        assert choice.repair is not RepairOperator.LOCAL_EXACT_PACK
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)


def test_local_exact_pack_is_offered_with_room() -> None:
    session = OperatorSession()
    repairs: set[RepairOperator] = set()
    for _ in range(len(SHIPPED_REPAIR)):
        choice = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
        repairs.add(choice.repair)
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)
    assert RepairOperator.LOCAL_EXACT_PACK in repairs


def test_scale_grows_with_stagnation_and_stays_inside_its_bounds() -> None:
    assert operator_scale(_context(strip_count=4, stagnation=0)) == C_MIN_DESTROY_STRIPS
    assert operator_scale(_context(strip_count=200, stagnation=0)) == C_MAX_DESTROY_STRIPS
    assert operator_scale(_context(strip_count=20, stagnation=0)) == 3
    assert operator_scale(_context(strip_count=20, stagnation=2)) == 7
    assert operator_scale(_context(strip_count=3, stagnation=9)) == 2


def test_remaining_fraction_bucket_quantizes_a_real_ratio() -> None:
    assert remaining_fraction_bucket(30.0, 30.0) == C_CONTEXT_FRACTION_STEPS
    assert remaining_fraction_bucket(0.0, 30.0) == 0
    assert remaining_fraction_bucket(15.0, 30.0) == C_CONTEXT_FRACTION_STEPS // 2
    assert remaining_fraction_bucket(-1.0, 30.0) == 0
    assert remaining_fraction_bucket(5.0, 0.0) == 0


# --- reward ------------------------------------------------------------------


def test_reward_is_the_lexicographic_improvement_with_no_time_divisor() -> None:
    after = _metrics(failed_nets=1, band_overflow=4, congestion=3.0)
    assert reward_vector(_outcome(_metrics(), after)) == (0.0, 3.0, 6.0, 5.0, 0.0)
    # The outcome record carries no seconds at all, so there is nothing a clock
    # could perturb; `observe` takes them separately, for telemetry only.
    assert "routing_seconds" not in OperatorOutcome.__dataclass_fields__


def test_a_clean_placement_outranks_every_other_improvement() -> None:
    clean = reward_vector(_outcome(_metrics(), _metrics(validator_clean=True, area=1200)))
    dirty = reward_vector(
        _outcome(_metrics(), _metrics(failed_nets=0, band_overflow=0, congestion=0.0))
    )
    assert clean > dirty


def test_area_credit_requires_a_clean_placement() -> None:
    assert reward_vector(_outcome(_metrics(), _metrics(area=500)))[4] == 0.0
    assert reward_vector(
        _outcome(_metrics(), _metrics(validator_clean=True, area=500))
    )[4] == 0.5


def test_regressions_never_produce_negative_reward() -> None:
    assert reward_vector(
        _outcome(_metrics(), _metrics(failed_nets=9, band_overflow=99, congestion=99.0))
    ) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_an_unapplied_outcome_costs_a_count_and_earns_nothing() -> None:
    session = OperatorSession()
    choice = session.select(_context())
    session.observe(choice, (1.0, 1.0, 1.0, 1.0, 1.0), applied=False)
    assert session.credit[f"count:{choice.destroy.value}"] == 1.0
    assert session.credit[f"reward:{choice.destroy.value}:0"] == 0.0
    assert session.applied == 0


def test_observe_and_select_credits_the_pending_choice_before_choosing() -> None:
    session = OperatorSession()
    first = session.observe_and_select(_metrics(), _context())
    assert session.pending == first
    # The first call has no baseline to compare against, so it credits nothing.
    assert all(
        value == 0.0 for key, value in session.credit.items() if key.startswith("count:")
    )
    second = session.observe_and_select(
        _metrics(failed_nets=1), _context(), routing_seconds=1.5
    )
    assert session.pending == second
    assert session.credit[f"count:{first.destroy.value}"] == 1.0
    assert session.choices == (first, second)
    assert session.routing_seconds == 1.5


def test_observe_and_select_with_no_baseline_only_selects() -> None:
    session = OperatorSession()
    choice = session.observe_and_select(_metrics(), _context())
    assert session.choices == (choice,)
    assert all(
        value == 0.0 for key, value in session.credit.items() if key.startswith("count:")
    )


# --- shared helpers ----------------------------------------------------------


def test_failed_endpoints_destroy_matches_the_existing_lns_neighbourhood() -> None:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    expected = select_lns_neighbourhood(
        _routing(), state.pair, state.gaps, problem, decoded, stagnation=0, grow_after=2
    )
    assert (
        destroy_strips(
            DestroyOperator.FAILED_ENDPOINTS,
            scale=problem.size,
            result=_routing(),
            pair=state.pair,
            gaps=state.gaps,
            problem=problem,
            decoded=decoded,
            band_target_width=decoded.width,
        )
        == expected
    )


def test_destroy_respects_its_scale_cap() -> None:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    assert (
        len(
            destroy_strips(
                DestroyOperator.FAILED_ENDPOINTS,
                scale=1,
                result=_routing(),
                pair=state.pair,
                gaps=state.gaps,
                problem=problem,
                decoded=decoded,
                band_target_width=decoded.width,
            )
        )
        <= 1
    )


def test_metrics_read_failed_nets_overflow_congestion_and_realized_area() -> None:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    feedback = FeedbackState(
        outline=(decoded.width, problem.outline_height),
        net_weight={},
        # (0, 0, 0) is the decoy: heavy, NOT on either wall cell, and inside the
        # outline whatever the decode width turns out to be.  A decoy outside the
        # outline raises in `FeedbackState.__post_init__`.
        cell_history={(2, 2, 0): 1.5, (2, 3, 0): 2.5, (0, 0, 0): 4.0},
    )
    metrics = metrics_from_evaluation(
        _routing(),
        decoded,
        feedback,
        outline_height=problem.outline_height,
        band_target_width=decoded.width - 2,
        validator_clean=False,
    )
    assert metrics.failed_nets == 1
    assert metrics.band_overflow == (
        max(0, decoded.used_height - problem.outline_height) + 2
    )
    assert metrics.congestion == 4.0
    assert metrics.area == decoded.width * decoded.used_height


def test_operator_tally_names_both_ledgers() -> None:
    session = OperatorSession()
    session.observe(session.select(_context()), (0.0,) * REWARD_RANKS, applied=True)
    tally = operator_tally(session)
    assert tally.startswith("destroy:")
    assert "|repair:" in tally
    for part in tally.split("|"):
        kind, name, count = part.split(":")
        assert kind in {"destroy", "repair"}
        assert name
        assert count.isdigit()
