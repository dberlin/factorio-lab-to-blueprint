from __future__ import annotations

import itertools
import math
import threading
import time
from dataclasses import FrozenInstanceError
from typing import cast

import pytest
from ortools.sat.python import cp_model

from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.compact_seed import (
    CompactSeedConfig,
    CompactSeedStatus,
    VariantDirectInsertTarget,
    solve_compact_seed,
)
from flab2bp.layout.freeform import _box, plan_strips
from flab2bp.layout.sequence_kernel import build_sequence_kernel
from flab2bp.layout.sequence_pair import (
    DirectInsertTarget,
    GapProfile,
    PlacementCostContext,
    PlacementProblem,
    SequencePair,
    decode_sequence_pair,
    decode_state,
)
from flab2bp.layout.sequence_solver import _placement_nets, _variant_search_inputs
from flab2bp.layout.strip_variants import StripVariant
from flab2bp.rates.candidates import build_candidates
from tests.layout.test_freeform import two_stage_spec


def _fixed_problem(
    sizes: tuple[tuple[int, int], ...] = ((3, 2), (2, 2), (1, 2)),
    *,
    height: int = 4,
    nets: tuple[tuple[int, int], ...] = ((0, 2),),
) -> PlacementProblem:
    return PlacementProblem(
        sizes=sizes,
        nets=nets,
        outline_height=height,
        area_lower_bound=sum(width * strip_height for width, strip_height in sizes),
    )


def _boxes_do_not_overlap(
    x: tuple[int, ...],
    y: tuple[int, ...],
    sizes: tuple[tuple[int, int], ...],
) -> bool:
    for first, second in itertools.combinations(range(len(sizes)), 2):
        first_width, first_height = sizes[first]
        second_width, second_height = sizes[second]
        if not (
            x[first] + first_width <= x[second]
            or x[second] + second_width <= x[first]
            or y[first] + first_height <= y[second]
            or y[second] + second_height <= y[first]
        ):
            return False
    return True


def _port(variant: StripVariant, item: str, kind: str) -> tuple[int, int]:
    plans = tuple(
        plan
        for plan in variant.attachment_plan
        if plan.lane.kind == kind and item in plan.lane.items
    )
    assert len(plans) == 1
    attachments = tuple(
        attachment for attachment in plans[0].attachments if attachment.item == item
    )
    assert len(attachments) == 1
    return attachments[0].cell


def _variant_problem() -> PlacementProblem:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=4)
    instance_ids, variant_tables = _variant_search_inputs(spec, strips, strip_len=4)
    placement_nets = _placement_nets(strips)
    sizes = tuple(_box(strip) for strip in strips)
    assert len(strips) == 2
    assert len(placement_nets) == 1
    return PlacementProblem(
        sizes=sizes,
        nets=tuple(endpoints for endpoints, _logical in placement_nets),
        outline_height=30,
        area_lower_bound=sum(
            min(
                (variant.box_width + sizes[index][0] - table[0].box_width)
                * (variant.box_height + sizes[index][1] - table[0].box_height)
                for variant in table
            )
            for index, table in enumerate(variant_tables)
        ),
        instance_ids=instance_ids,
        logical_net_ids=tuple(logical for _endpoints, logical in placement_nets),
        variant_tables=variant_tables,
    )


def test_config_is_immutable_and_validates_exact_types_and_ranges() -> None:
    config = CompactSeedConfig()
    assert config.max_deterministic_time == 5.0
    with pytest.raises(FrozenInstanceError):
        config.max_deterministic_time = 1.0  # type: ignore[misc]

    for value in (True, 1, 0.0, -1.0, math.inf, math.nan):
        with pytest.raises(ValueError, match="deterministic"):
            CompactSeedConfig(max_deterministic_time=value)

    problem = _fixed_problem()
    with pytest.raises(ValueError, match="base seed"):
        solve_compact_seed(problem, base_seed=True, attempt=0)
    with pytest.raises(ValueError, match="attempt"):
        solve_compact_seed(problem, base_seed=1, attempt=True)
    with pytest.raises(ValueError, match="attempt"):
        solve_compact_seed(problem, base_seed=1, attempt=-1)


def test_falsey_non_configs_are_rejected_and_falsey_cancellation_is_preserved() -> None:
    problem = _fixed_problem()
    for falsey in (False, 0, ()):
        with pytest.raises(ValueError, match="config"):
            solve_compact_seed(
                problem,
                base_seed=1,
                attempt=0,
                config=cast(CompactSeedConfig, falsey),
            )

    class FalseyCancellation:
        def __bool__(self) -> bool:
            return False

        def __call__(self) -> bool:
            return True

    cancelled = solve_compact_seed(
        problem,
        base_seed=1,
        attempt=0,
        cancelled=FalseyCancellation(),
    )
    assert cancelled.status is CompactSeedStatus.CANCELLED
    assert cancelled.state is None


def test_int64_model_boundaries_fail_before_ortools_model_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_model() -> cp_model.CpModel:
        raise AssertionError("OR-Tools model constructed before module validation")

    monkeypatch.setattr(cp_model, "CpModel", unexpected_model)
    cases = (
        PlacementProblem(((1, 1),), (), 2**63, 1),
        PlacementProblem((((1 << 63) - 1, 1), (1, 1)), (), 1, 1),
        PlacementProblem(((1 << 62, 1),), ((0, 0),), 1, 1),
        PlacementProblem(((1 << 60, 1),), ((0, 0),) * 10, 1, 1),
    )
    for problem in cases:
        with pytest.raises(ValueError, match="signed 64-bit"):
            solve_compact_seed(problem, base_seed=1, attempt=0)


def test_inflight_cancellation_stops_solver_and_joins_watcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    solve_started = threading.Event()
    cancellation_enabled = threading.Event()
    stop_called = threading.Event()

    def fake_solve(self: cp_model.CpSolver, model: cp_model.CpModel) -> cp_model.CpSolverStatus:
        del self, model
        solve_started.set()
        assert stop_called.wait(1.0), "cancellation watcher did not stop the blocking solve"
        return cp_model.UNKNOWN

    def fake_stop_search(self: cp_model.CpSolver) -> None:
        del self
        stop_called.set()

    def enable_cancellation() -> None:
        assert solve_started.wait(1.0)
        cancellation_enabled.set()

    monkeypatch.setattr(cp_model.CpSolver, "solve", fake_solve)
    monkeypatch.setattr(cp_model.CpSolver, "stop_search", fake_stop_search)
    trigger = threading.Thread(target=enable_cancellation)
    trigger.start()
    result = solve_compact_seed(
        _fixed_problem(),
        base_seed=1,
        attempt=0,
        cancelled=cancellation_enabled.is_set,
    )
    trigger.join()

    assert result.status is CompactSeedStatus.CANCELLED
    assert result.state is None
    assert stop_called.is_set()
    assert not any(
        thread.name == "compact-seed-cancellation" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_inflight_cancellation_callback_exception_stops_solver_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CancellationError(RuntimeError):
        pass

    solve_started = threading.Event()
    stop_called = threading.Event()
    callback_calls = 0

    def cancellation() -> bool:
        nonlocal callback_calls
        callback_calls += 1
        if solve_started.is_set():
            raise CancellationError("cancel callback failed")
        return False

    def fake_solve(self: cp_model.CpSolver, model: cp_model.CpModel) -> cp_model.CpSolverStatus:
        del self, model
        solve_started.set()
        assert stop_called.wait(1.0), "callback failure did not stop the blocking solve"
        return cp_model.UNKNOWN

    def fake_stop_search(self: cp_model.CpSolver) -> None:
        del self
        stop_called.set()

    monkeypatch.setattr(cp_model.CpSolver, "solve", fake_solve)
    monkeypatch.setattr(cp_model.CpSolver, "stop_search", fake_stop_search)
    with pytest.raises(CancellationError, match="cancel callback failed"):
        solve_compact_seed(
            _fixed_problem(),
            base_seed=1,
            attempt=0,
            cancelled=cancellation,
        )
    assert callback_calls >= 2
    assert stop_called.is_set()
    assert not any(
        thread.name == "compact-seed-cancellation" and thread.is_alive()
        for thread in threading.enumerate()
    )


def test_fixed_height_model_has_exact_non_overlap_and_validated_zero_gap_state() -> None:
    problem = _fixed_problem()
    result = solve_compact_seed(
        problem,
        base_seed=31,
        attempt=0,
        config=CompactSeedConfig(max_deterministic_time=0.2),
    )

    assert result.status in (CompactSeedStatus.FEASIBLE, CompactSeedStatus.OPTIMAL)
    assert result.state is not None
    assert result.state.base_seed == 31
    assert result.state.stage_index == 0
    assert result.state.gaps == GapProfile.zero(problem.size)
    assert result.state.variant_indices == (0,) * problem.size
    assert result.diagnostics.solved_x is not None
    assert result.diagnostics.solved_y is not None
    assert result.diagnostics.solved_sizes is not None
    assert _boxes_do_not_overlap(
        result.diagnostics.solved_x,
        result.diagnostics.solved_y,
        result.diagnostics.solved_sizes,
    )
    assert all(
        y + strip_height <= problem.outline_height
        for y, (_width, strip_height) in zip(
            result.diagnostics.solved_y,
            result.diagnostics.solved_sizes,
            strict=True,
        )
    )
    decoded = decode_state(problem, result.state)
    assert decoded.used_height <= problem.outline_height
    assert _boxes_do_not_overlap(decoded.x, decoded.y, problem.selected_sizes((0,) * problem.size))


def test_rank_vectors_convert_directly_to_the_genuine_sequence_pair_relations() -> None:
    problem = _fixed_problem(sizes=((2, 1), (1, 2), (2, 2), (1, 1)), height=3, nets=())
    result = solve_compact_seed(
        problem,
        base_seed=19,
        attempt=2,
        config=CompactSeedConfig(max_deterministic_time=0.2),
    )

    assert result.state is not None
    assert result.diagnostics.positive_ranks is not None
    assert result.diagnostics.negative_ranks is not None
    positive_ranks = result.diagnostics.positive_ranks
    negative_ranks = result.diagnostics.negative_ranks
    assert result.state.pair.positive == tuple(
        sorted(range(problem.size), key=positive_ranks.__getitem__)
    )
    assert result.state.pair.negative == tuple(
        sorted(range(problem.size), key=negative_ranks.__getitem__)
    )

    decoded = decode_state(problem, result.state)
    sizes = problem.selected_sizes(result.state.variant_indices)
    for first, second in itertools.combinations(range(problem.size), 2):
        positive_before = positive_ranks[first] < positive_ranks[second]
        negative_before = negative_ranks[first] < negative_ranks[second]
        if positive_before and negative_before:
            assert decoded.x[first] + sizes[first][0] <= decoded.x[second]
        elif not positive_before and not negative_before:
            assert decoded.x[second] + sizes[second][0] <= decoded.x[first]
        elif positive_before:
            assert decoded.y[second] + sizes[second][1] <= decoded.y[first]
        else:
            assert decoded.y[first] + sizes[first][1] <= decoded.y[second]


def test_variable_variants_select_atomic_dimensions_identities_and_authoritative_ports() -> None:
    problem = _variant_problem()
    result = solve_compact_seed(
        problem,
        base_seed=73,
        attempt=1,
        config=CompactSeedConfig(max_deterministic_time=0.3),
    )

    assert result.state is not None
    selected_sizes = problem.selected_sizes(result.state.variant_indices)
    assert result.diagnostics.solved_sizes == selected_sizes
    assert result.diagnostics.selected_variant_ids == problem.selected_variant_ids(
        result.state.variant_indices
    )
    source_variant = problem.variant(0, result.state.variant_indices[0])
    destination_variant = problem.variant(1, result.state.variant_indices[1])
    item = problem.logical_net_ids[0].item
    assert result.diagnostics.selected_port_offsets == (
        (
            *_port(source_variant, item, "output"),
            *_port(destination_variant, item, "input"),
        ),
    )


def test_width_has_lexicographic_dominance_over_every_secondary_proxy_term() -> None:
    problem = _fixed_problem()
    result = solve_compact_seed(
        problem,
        base_seed=101,
        attempt=3,
        config=CompactSeedConfig(max_deterministic_time=0.3),
    )
    assert result.state is not None

    minimum_width = min(
        decoded.width
        for positive in itertools.permutations(range(problem.size))
        for negative in itertools.permutations(range(problem.size))
        if (
            decoded := decode_sequence_pair(
                SequencePair(positive, negative),
                GapProfile.zero(problem.size),
                problem.sizes,
                outline_height=problem.outline_height,
            )
        ).used_height
        <= problem.outline_height
    )
    decoded = decode_state(problem, result.state)
    assert decoded.width == minimum_width
    assert result.diagnostics.width_weight > result.diagnostics.secondary_upper_bound


def test_same_attempt_repeats_identically_and_attempts_derive_diverse_states() -> None:
    problem = _fixed_problem(sizes=((1, 1),) * 4, height=2, nets=())
    config = CompactSeedConfig(max_deterministic_time=0.2)

    first = solve_compact_seed(problem, base_seed=20260825, attempt=0, config=config)
    repeat = solve_compact_seed(problem, base_seed=20260825, attempt=0, config=config)
    assert first.state is not None
    assert repeat.state == first.state
    assert repeat.diagnostics.solver_seed == first.diagnostics.solver_seed
    assert repeat.diagnostics.objective_value == first.diagnostics.objective_value

    states = {
        solve_compact_seed(problem, base_seed=20260825, attempt=attempt, config=config).state
        for attempt in range(6)
    }
    assert None not in states
    assert len(states) >= 2


def test_infeasible_cancelled_deadline_and_no_incumbent_return_no_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    infeasible = _fixed_problem(sizes=((2, 2),), height=1, nets=())
    result = solve_compact_seed(
        infeasible,
        base_seed=1,
        attempt=0,
        config=CompactSeedConfig(max_deterministic_time=0.05),
    )
    assert result.status is CompactSeedStatus.INFEASIBLE
    assert result.state is None

    problem = _fixed_problem()
    cancelled = solve_compact_seed(problem, base_seed=1, attempt=0, cancelled=lambda: True)
    assert cancelled.status is CompactSeedStatus.CANCELLED
    assert cancelled.state is None
    expired = solve_compact_seed(
        problem,
        base_seed=1,
        attempt=0,
        absolute_deadline=time.monotonic() - 1.0,
    )
    assert expired.status is CompactSeedStatus.CANCELLED
    assert expired.state is None

    monkeypatch.setattr(cp_model.CpSolver, "solve", lambda self, model: cp_model.UNKNOWN)
    unknown = solve_compact_seed(problem, base_seed=1, attempt=0)
    assert unknown.status is CompactSeedStatus.UNKNOWN
    assert unknown.state is None


def test_cp_coordinate_direct_success_is_not_accepted_as_zero_gap_decoded_truth() -> None:
    problem = _fixed_problem(sizes=((2, 1), (2, 1), (2, 1)), height=2, nets=((0, 1),))
    target = DirectInsertTarget((0, 1), 0, 1, 0, 0, 2, 2)
    eligibility = (VariantDirectInsertTarget(0, 0, target),)
    result = solve_compact_seed(
        problem,
        base_seed=99,
        attempt=10,
        direct_eligibility=eligibility,
        config=CompactSeedConfig(max_deterministic_time=0.1),
    )

    assert result.state is not None
    assert result.diagnostics.cp_direct_keys == frozenset({(0, 1)})
    assert result.diagnostics.decoded_direct_keys == frozenset()
    assert decode_state(problem, result.state).direct == frozenset()

    without_eligibility = solve_compact_seed(
        problem,
        base_seed=99,
        attempt=10,
        direct_eligibility=(),
        config=CompactSeedConfig(max_deterministic_time=0.1),
    )
    assert without_eligibility.diagnostics.cp_direct_keys == frozenset()
    assert without_eligibility.diagnostics.decoded_direct_keys == frozenset()


_REFINERY_URL = "https://factoriolab.github.io/dsp/list?z=eJxFyrEKwkAQRdG.meJVM0GxmuYtxk4SQXFbdRGJSyCgaDPfLqJod7jc0XmGqYzOI2ZzBezt598LNPrlDs3vyLBPLo5WqhMq1TNULofilKk8vEPGCQNu4BrcgntwCF6R2kgrpD7SRmqdPAdjGb3c3ewFUJ8mgA__&v=11"


@pytest.mark.slow
def test_real_refinery_height_30_seed_is_cython_decodable_without_witness_hint() -> None:
    spec = build_candidates(load_vendored(), parse_url(_REFINERY_URL), count=3).candidates[2]
    strips = plan_strips(spec, strip_len=4)
    instance_ids, variant_tables = _variant_search_inputs(spec, strips, strip_len=4)
    sizes = tuple(_box(strip) for strip in strips)
    placement_nets = _placement_nets(strips)
    problem = PlacementProblem(
        sizes=sizes,
        nets=tuple(endpoints for endpoints, _logical in placement_nets),
        outline_height=30,
        area_lower_bound=sum(
            min(
                (variant.box_width + sizes[index][0] - table[0].box_width)
                * (variant.box_height + sizes[index][1] - table[0].box_height)
                for variant in table
            )
            for index, table in enumerate(variant_tables)
        ),
        instance_ids=instance_ids,
        logical_net_ids=tuple(logical for _endpoints, logical in placement_nets),
        variant_tables=variant_tables,
    )

    result = solve_compact_seed(
        problem,
        base_seed=2026082502,
        attempt=5,
        config=CompactSeedConfig(max_deterministic_time=0.5),
    )
    assert result.state is not None
    context = PlacementCostContext(
        net_weights=(1.0,) * len(problem.nets),
        net_pairs=problem.nets,
        history_outline=(0, problem.outline_height),
        history_summed_area=(0.0,) * (problem.outline_height + 1),
    )
    kernel = build_sequence_kernel(problem, context)
    assert kernel.backend == "cython"
    incumbent = kernel.score_state(result.state)
    assert incumbent.decoded.used_height <= problem.outline_height
    assert incumbent.state.pair == result.state.pair
