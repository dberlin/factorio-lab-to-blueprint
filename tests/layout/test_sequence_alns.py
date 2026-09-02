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
    C_DUCB_EXPLORATION,
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


def test_band_boundary_is_a_shipped_arm_the_selector_can_dispatch() -> None:
    """BAND_BOUNDARY is offered as the second arm AND has a dispatch branch.

    BAND_BOUNDARY ships (plan line 16, spec section 5.3) so the selector offers
    it as the second arm from the very first pair of selections.  This test is
    the contract in both halves: the selection, and a dispatch that answers with
    strips rather than raising.  A placement that fits its band and its outline
    is not the operator's evidence, so the answer there is the empty set.
    """
    session = OperatorSession()
    session.observe(session.select(_context()), (0.0,) * REWARD_RANKS, applied=True)
    assert session.select(_context()).destroy is DestroyOperator.BAND_BOUNDARY

    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    assert (
        destroy_strips(
            DestroyOperator.BAND_BOUNDARY,
            scale=4,
            result=_routing(),
            pair=state.pair,
            gaps=state.gaps,
            problem=problem,
            decoded=decoded,
            band_target_width=decoded.width,
        )
        == frozenset()
    )


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


def test_the_less_played_arm_wins_when_every_mean_is_tied_at_zero() -> None:
    session = OperatorSession()
    for _ in range(len(SHIPPED_DESTROY)):
        choice = session.select(_context())
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)
    # Both arms have identical (zero) means, so the less-played arm wins on the bonus.
    first = session.select(_context())
    session.observe(first, (0.0,) * REWARD_RANKS, applied=True)
    assert session.select(_context()).destroy is not first.destroy


def test_a_tie_on_every_nonzero_mean_is_broken_by_the_exploration_bonus() -> None:
    """The bonus decides when, and only when, every mean is equal.

    The zero-mean case above cannot tell a working bonus from a dead one that
    falls through to declaration order, because there the less-played arm is
    also the first-declared one.  Here the winner is the SECOND-declared arm, so
    only the bonus can have chosen it.
    """
    session = OperatorSession()
    for _ in range(3):
        choice = session.select(_context())
        session.observe(choice, (0.0, 1.0, 0.0, 0.0, 0.0), applied=True)
    # Every arm has been credited the same reward, so every mean is exactly 1.0,
    # but BAND_BOUNDARY has been played once against FAILED_ENDPOINTS' twice.
    assert math.isclose(session.credit["reward:failed-endpoints:1"], 1.81, rel_tol=1e-12)
    assert math.isclose(session.credit["reward:band-boundary:1"], 0.9, rel_tol=1e-12)
    assert session.select(_context()).destroy is DestroyOperator.BAND_BOUNDARY


def test_the_exploration_bonus_never_outvotes_even_the_last_mean() -> None:
    """A difference on rank 4 beats a bonus, which is the whole lexicographic point."""
    session = OperatorSession()
    first = session.select(_context())
    session.observe(first, (0.0,) * REWARD_RANKS, applied=True)
    second = session.select(_context())
    session.observe(second, (0.0, 0.0, 0.0, 0.0, 1.0), applied=True)
    # `first` is now the less-played arm and so carries the larger bonus, but
    # `second` leads on the lowest-priority mean; the mean still wins.
    assert session.credit[f"count:{first.destroy.value}"] < session.credit[
        f"count:{second.destroy.value}"
    ]
    assert session.select(_context()).destroy is second.destroy


def test_the_selector_constants_are_pinned_at_their_reviewed_values() -> None:
    """Literals on purpose: a review approved these exact numbers.

    The exploration coefficient is a positive scale factor on the FINAL
    lexicographic component, so any positive value orders the arms identically
    and no selection test can distinguish 0.5 from 0.001.  Pinning the literal
    is therefore the only way a silent retune goes red.
    """
    assert C_DUCB_DISCOUNT == 0.9
    assert C_DUCB_EXPLORATION == 0.5


def test_a_zero_exploration_coefficient_collapses_to_declaration_order() -> None:
    """What the bonus buys, stated as behaviour: without it, ties never rotate."""
    session = OperatorSession(exploration=0.0)
    for _ in range(len(SHIPPED_DESTROY)):
        choice = session.select(_context())
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)
    assert session.select(_context()).destroy is DestroyOperator.FAILED_ENDPOINTS


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
    # 1 + 0.9 + 0.81 + 0.729, written out rather than derived from the module, so
    # that retuning the discount has to come here and change the number.
    assert math.isclose(
        session.credit[f"count:{played.destroy.value}"], 3.439, rel_tol=1e-12
    )


def test_discounting_decays_the_reward_sums_and_not_only_the_counts() -> None:
    """A decayed count over an undecayed sum would inflate every stale mean."""
    session = OperatorSession()
    first = session.select(_context())
    session.observe(first, (0.0, 1.0, 0.0, 0.0, 0.0), applied=True)
    second = session.select(_context())
    session.observe(second, (0.0, 4.0, 0.0, 0.0, 0.0), applied=True)
    # One observation has passed since the first arm was credited, so both its
    # count and its rank-1 sum carry exactly one discount.
    assert math.isclose(session.credit["count:failed-endpoints"], 0.9, rel_tol=1e-12)
    assert math.isclose(session.credit["reward:failed-endpoints:1"], 0.9, rel_tol=1e-12)
    # The arm credited last carries none.
    assert math.isclose(session.credit["count:band-boundary"], 1.0, rel_tol=1e-12)
    assert math.isclose(session.credit["reward:band-boundary:1"], 4.0, rel_tol=1e-12)


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


def test_rank_zero_credits_the_edge_into_clean_and_not_staying_clean() -> None:
    """Rank 0 pays for BECOMING valid, so a clean incumbent cannot farm it.

    Without the `not before.validator_clean` half of the trigger, every operator
    applied to an already-clean placement would score a perfect rank 0 and the
    selector would stop discriminating the moment the search first went clean.
    """
    already_clean = _metrics(validator_clean=True)
    stays_clean = _metrics(validator_clean=True, failed_nets=1)
    assert reward_vector(_outcome(already_clean, stays_clean))[0] == 0.0
    # The improvement below rank 0 is still credited normally.
    assert reward_vector(_outcome(already_clean, stays_clean))[1] == 3.0
    # The same `after`, reached from a dirty `before`, IS the edge.
    assert reward_vector(_outcome(_metrics(), stays_clean))[0] == 1.0


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


def test_the_scale_cap_keeps_the_highest_ranked_strips_and_drops_the_tail() -> None:
    """Capping is a head slice of the operator's own ranking, never a tail one.

    `FAILED_ENDPOINTS` ranks by sorted strip index, so the head is the low
    indices.  Task 6's `BAND_BOUNDARY` will rank by overflow contribution, where
    keeping the tail would drop the worst offender and keep the mildest -- the
    exact inversion of the operator, and invisible unless a test names the set.
    """
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)

    def destroy(scale: int) -> frozenset[int]:
        return destroy_strips(
            DestroyOperator.FAILED_ENDPOINTS,
            scale=scale,
            result=_routing(),
            pair=state.pair,
            gaps=state.gaps,
            problem=problem,
            decoded=decoded,
            band_target_width=decoded.width,
        )

    assert destroy(problem.size) == frozenset({0, 1, 2, 3})
    assert destroy(2) == frozenset({0, 1})
    assert destroy(3) == frozenset({0, 1, 2})


def test_destroy_refuses_a_scale_below_one() -> None:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    with pytest.raises(ValueError, match="positive integer"):
        destroy_strips(
            DestroyOperator.FAILED_ENDPOINTS,
            scale=0,
            result=_routing(),
            pair=state.pair,
            gaps=state.gaps,
            problem=problem,
            decoded=decoded,
            band_target_width=decoded.width,
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


# --- band boundary -----------------------------------------------------------


def _band_destroy(*, band_target_width: int, scale: int = 4) -> frozenset[int]:
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    return destroy_strips(
        DestroyOperator.BAND_BOUNDARY,
        scale=scale,
        result=_routing(),
        pair=state.pair,
        gaps=state.gaps,
        problem=problem,
        decoded=decoded,
        band_target_width=band_target_width,
    )


def test_band_boundary_is_empty_when_the_placement_already_fits() -> None:
    problem = _problem()
    decoded = decode_state(problem, AnnealState.initial(problem.size, 7))
    assert _band_destroy(band_target_width=decoded.width + 10) == frozenset()


def test_band_boundary_selects_the_strips_past_the_target_width() -> None:
    problem = _problem()
    decoded = decode_state(problem, AnnealState.initial(problem.size, 7))
    target = max(1, decoded.width - 1)
    selected = _band_destroy(band_target_width=target)
    assert selected
    assert all(decoded.x[strip] + problem.sizes[strip][0] > target for strip in selected)


def test_band_boundary_falls_back_to_the_widest_edges_when_nothing_exceeds() -> None:
    problem = _problem()
    # Target equals the width, so no strip exceeds it; an outline overflow is
    # what makes the operator applicable, and this fixture has none, so the
    # operator is empty.  Force the overflow branch with a tiny outline.
    tight = PlacementProblem(
        sizes=problem.sizes,
        nets=problem.nets,
        outline_height=1,
        area_lower_bound=problem.area_lower_bound,
    )
    tight_state = AnnealState.initial(tight.size, 7)
    tight_decoded = decode_state(tight, tight_state)
    selected = destroy_strips(
        DestroyOperator.BAND_BOUNDARY,
        scale=2,
        result=_routing(),
        pair=tight_state.pair,
        gaps=tight_state.gaps,
        problem=tight,
        decoded=tight_decoded,
        band_target_width=tight_decoded.width,
    )
    assert 0 < len(selected) <= 2


def test_band_boundary_excludes_a_strip_that_ends_exactly_on_the_target() -> None:
    """"Exceeds" is strict: a right edge that lands on the target is inside it."""
    problem = _problem()
    decoded = decode_state(problem, AnnealState.initial(problem.size, 7))
    edges = [decoded.x[strip] + problem.sizes[strip][0] for strip in range(problem.size)]
    target = min(edges)
    # The fixture must straddle the boundary or the assertion below is vacuous.
    assert max(edges) > target
    selected = _band_destroy(band_target_width=target)
    assert selected == frozenset(
        strip for strip in range(problem.size) if edges[strip] > target
    )


def test_band_boundary_keeps_the_worst_offenders_when_it_is_capped() -> None:
    """A small `scale` must keep the strips that own the overflow, not the mildest."""
    problem = _problem()
    decoded = decode_state(problem, AnnealState.initial(problem.size, 7))
    worst_two = {
        strip
        for _edge, strip in sorted(
            (-(decoded.x[strip] + problem.sizes[strip][0]), strip)
            for strip in range(problem.size)
        )[:2]
    }
    selected = _band_destroy(band_target_width=1, scale=2)
    assert len(selected) == 2
    assert selected == worst_two


def test_band_boundary_refuses_a_scale_below_one() -> None:
    """The scale guard runs before dispatch, so the new branch inherits it."""
    with pytest.raises(ValueError, match="positive integer"):
        _band_destroy(band_target_width=1, scale=0)
