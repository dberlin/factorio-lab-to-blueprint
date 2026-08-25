from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import cast

import pytest

import flab2bp.layout.freeform as freeform_module
import flab2bp.layout.sequence_solver as sequence_solver_module
from flab2bp.bench.corpus import entry
from flab2bp.dsp import catalog
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout import slots, validate
from flab2bp.layout.base import NoValidLayout, PlacedBuilding, Placement
from flab2bp.layout.freeform import (
    _box,
    _build_prepared,
    _greedy_pack,
    _nets_between,
    _Pack,
    _prepare_routing_problem,
    _PreparedRoutingProblem,
    _Unpowerable,
    plan_strips,
)
from flab2bp.layout.global_router import GlobalRouteResult, route_global
from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    LogicalNetId,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
    feedback_cost_context,
    select_lns_neighbourhood,
    select_split_candidate,
)
from flab2bp.layout.sequence_pair import (
    AnnealConfig,
    AnnealIncumbent,
    AnnealStageResult,
    AnnealState,
    DecodedPlacement,
    DirectInsertTarget,
    GapProfile,
    PlacementCostContext,
    PlacementKey,
    PlacementProblem,
    SearchEnergy,
    SequencePair,
    StageBoundaryUpdate,
    anneal_stage,
    apply_variant_move,
    decode_sequence_pair,
    decode_state,
    derive_stage_seed,
    repair_neighbourhood,
    split_stage_boundary,
)
from flab2bp.layout.sequence_solver import (
    DetailedStageResult,
    ExpansionBudget,
    SequencePairLayout,
    SequenceSearchResult,
    SequenceSolver,
    SequenceSolverConfig,
    StageAdapters,
    ValidationVerdict,
    _decoded_pack,
    _production_run,
    _ProductionCandidate,
    _rebuild_stage_problem_nets,
    _route_detailed_candidate,
    _selected_direct_targets,
    _selected_strips,
    _variant_search_inputs,
)
from flab2bp.layout.strip_variants import (
    StripFamilyId,
    StripInstanceId,
    generate_strip_families,
    partition_strip_family,
    variants_for_count,
)
from flab2bp.rates.candidates import build_candidates
from flab2bp.spec import BuildSpec, MachineGroup
from tests.layout.test_freeform import proliferated_spec, two_stage_spec

Prepared = tuple[int, DecodedPlacement]


def _placement(*, area: int, belt_tiles: int, valid: bool = True) -> Placement:
    return Placement(
        buildings=(
            PlacedBuilding(
                item_id=1,
                model_index=1,
                x=0,
                y=0,
                width=area,
                height=1,
            ),
        ),
        stats={
            "belt_tiles": float(belt_tiles),
            "validator_clean": float(valid),
        },
    )


def _routing(
    status: DetailedRouteStatus,
    *,
    expansions: int = 0,
    geometric_failure: bool = False,
) -> DetailedRouteResult:
    failures: tuple[NetFailure, ...] = ()
    if status is not DetailedRouteStatus.ROUTED:
        net = NetId(0, 0, "item", NetRole.INTERNAL, 0)
        failures = (
            NetFailure(
                net_id=net,
                kind=(
                    RouteFailureKind.CONGESTION_WALL
                    if geometric_failure
                    else RouteFailureKind.BUDGET
                ),
                wall=((0, 0, 0),) if geometric_failure else (),
                blocking_nets=(),
                expansions=expansions,
            ),
        )
    return DetailedRouteResult(
        status=status,
        routed=(),
        failures=failures,
        iterations=1,
        expansions=expansions,
    )


def _global(
    *, overflow: int = 0, expansions: int = 0, cancelled: bool = False
) -> GlobalRouteResult:
    return GlobalRouteResult(
        net_results=(),
        paths={},
        overflow_cells=overflow,
        total_overflow=overflow,
        max_overflow=overflow,
        unreachable_ports=0,
        rounds=1,
        expansions=expansions,
        exhausted_budget=False,
        hot_cells=(),
        hot_regions=(),
        cancelled=cancelled,
    )


@dataclass
class _FakeRouting:
    detailed_results: tuple[DetailedStageResult, ...] = ()
    spend_allowance: bool = False
    stage_trace: list[int] = field(default_factory=list)
    global_allowances: list[int] = field(default_factory=list)
    detailed_allowances: list[int] = field(default_factory=list)
    feedback_seen: list[FeedbackState] = field(default_factory=list)
    _detailed_index: int = 0

    def prepare(self, height: int, decoded: DecodedPlacement) -> Prepared:
        self.stage_trace.append(height)
        return height, decoded

    def global_route(
        self, prepared: Prepared, feedback: FeedbackState, allowance: int
    ) -> GlobalRouteResult:
        del prepared
        self.feedback_seen.append(feedback)
        self.global_allowances.append(allowance)
        return _global(expansions=allowance if self.spend_allowance else 0)

    def detailed_route(self, prepared: Prepared, allowance: int) -> DetailedStageResult:
        del prepared
        self.detailed_allowances.append(allowance)
        if not self.detailed_results:
            result = DetailedStageResult(_routing(DetailedRouteStatus.BUDGET), None)
        else:
            result = self.detailed_results[
                min(self._detailed_index, len(self.detailed_results) - 1)
            ]
        self._detailed_index += 1
        if self.spend_allowance:
            result = DetailedStageResult(
                routing=DetailedRouteResult(
                    status=result.routing.status,
                    routed=result.routing.routed,
                    failures=result.routing.failures,
                    iterations=result.routing.iterations,
                    expansions=allowance,
                ),
                placement=result.placement,
            )
        return result

    def validate(self, placement: Placement) -> ValidationVerdict:
        if placement.stats.get("validator_clean") == 1.0:
            return ValidationVerdict(ok=True, failed_checks=())
        return ValidationVerdict(ok=False, failed_checks=("fake.invalid",))

    def adapters(self) -> StageAdapters[Prepared]:
        return StageAdapters(
            prepare=self.prepare,
            global_route=self.global_route,
            detailed_route=self.detailed_route,
            validate=self.validate,
        )


def _solver(
    fake: _FakeRouting,
    *,
    heights: tuple[int, ...] = (40, 60, 80),
    budget: ExpansionBudget | None = None,
    config: SequenceSolverConfig | None = None,
    deadline_reached: Callable[[], bool] | None = None,
) -> SequenceSolver[Prepared]:
    return SequenceSolver(
        heights=heights,
        problem_for_height=lambda height: PlacementProblem(
            sizes=((1, 1),),
            nets=((0, 0),),
            outline_height=height,
            area_lower_bound=1,
        ),
        adapters=fake.adapters(),
        expansion_budget=budget or ExpansionBudget(total=1_000),
        config=config
        or SequenceSolverConfig(
            stages=6,
            moves_per_stage=1,
            restarts_per_height=2,
            global_elites=1,
        ),
        deadline_reached=deadline_reached or (lambda: False),
    )


def test_every_height_gets_one_stage_before_any_second_stage() -> None:
    fake = _FakeRouting()
    with pytest.raises(NoValidLayout):
        _solver(fake).search(max_stages=4)
    assert fake.stage_trace[:3] == [40, 60, 80]


def test_every_stage_ends_with_exactly_one_detailed_route() -> None:
    fake = _FakeRouting()
    with pytest.raises(NoValidLayout):
        _solver(fake, heights=(40,)).search(max_stages=3)
    assert len(fake.detailed_allowances) == 3


def test_detailed_route_still_runs_when_global_spends_the_stage_allowance() -> None:
    fake = _FakeRouting(spend_allowance=True)
    with pytest.raises(NoValidLayout):
        _solver(fake, heights=(40,), budget=ExpansionBudget(total=100)).search(max_stages=3)
    assert fake.detailed_allowances == [0]


def test_proxy_candidate_cannot_displace_exact_incumbent() -> None:
    exact = _placement(area=100, belt_tiles=50)
    proxy = _placement(area=90, belt_tiles=20)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),
            DetailedStageResult(_routing(DetailedRouteStatus.STRANDED), proxy),
        )
    )
    result = _solver(fake, heights=(40,)).search(max_stages=2)
    assert result.placement is exact
    assert result.exact_key == (100, 50)


def test_exact_incumbents_compare_only_area_then_belt_tiles() -> None:
    first = _placement(area=100, belt_tiles=50)
    better_belts = _placement(area=100, belt_tiles=40)
    worse_area = _placement(area=101, belt_tiles=1)
    fake = _FakeRouting(
        detailed_results=tuple(
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), placement)
            for placement in (first, better_belts, worse_area)
        )
    )
    result = _solver(fake, heights=(40,)).search(max_stages=3)
    assert result.placement is better_belts
    assert result.exact_key == (100, 40)


def test_validator_rejection_never_establishes_an_exact_incumbent() -> None:
    invalid = _placement(area=10, belt_tiles=2, valid=False)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), invalid),)
    )
    with pytest.raises(NoValidLayout):
        _solver(fake, heights=(40,)).search(max_stages=1)


def test_sequence_stage_context_supplies_history_and_direct_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = DirectInsertTarget((0, 1), 0, 1, 0, 0, 1, 1)
    contexts: list[PlacementCostContext] = []
    real_anneal_stage = anneal_stage

    def capture_context(
        problem: PlacementProblem,
        state: AnnealState,
        config: AnnealConfig,
        context: PlacementCostContext | None = None,
    ) -> AnnealStageResult:
        assert context is not None
        contexts.append(context)
        return real_anneal_stage(problem, state, config, context)

    monkeypatch.setattr(sequence_solver_module, "anneal_stage", capture_context)
    fake = _FakeRouting()
    solver = SequenceSolver(
        heights=(2,),
        problem_for_height=lambda height: PlacementProblem(
            sizes=((1, 1), (1, 1)),
            nets=((0, 1),),
            outline_height=height,
            area_lower_bound=1,
        ),
        adapters=fake.adapters(),
        expansion_budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        initial_feedback=lambda _problem: FeedbackState(
            outline=(2, 2),
            net_weight={},
            cell_history={(0, 0, 0): 2.5},
        ),
        direct_targets=(target,),
    )

    with pytest.raises(NoValidLayout):
        solver.search(max_stages=1)

    assert len(contexts) == 1
    assert contexts[0].direct_targets == (target,)
    assert contexts[0].history_summed_area[-1] == 2.5


def test_stage_routes_cannot_spend_final_twenty_five_percent() -> None:
    budget = ExpansionBudget(total=100)
    fake = _FakeRouting(spend_allowance=True)
    with pytest.raises(NoValidLayout):
        _solver(fake, heights=(40,), budget=budget).search(max_stages=20)
    assert budget.final_reserved == 25
    assert budget.spent == 75
    assert max(fake.global_allowances) == 75
    assert sum(fake.global_allowances) + sum(fake.detailed_allowances) == 75


def test_discovery_reservations_are_equal_and_unused_budget_is_shared_afterward() -> None:
    budget = ExpansionBudget(total=101)
    fake = _FakeRouting()
    with pytest.raises(NoValidLayout):
        _solver(fake, budget=budget).search(max_stages=4)
    assert budget.discovery_by_height == {40: 25, 60: 25, 80: 25}
    assert budget.final_reserved == 26
    assert fake.global_allowances[:3] == [25, 25, 25]
    assert fake.global_allowances[3] == 75


def test_selected_global_cancellation_stops_before_detailed_or_feedback() -> None:
    feedback_seen: list[FeedbackState] = []
    detailed_calls = 0
    budget = ExpansionBudget(100)

    def global_route(
        prepared: Prepared,
        feedback: FeedbackState,
        allowance: int,
    ) -> GlobalRouteResult:
        del prepared, allowance
        feedback_seen.append(feedback)
        return _global(expansions=3, cancelled=True)

    def detailed_route(
        prepared: Prepared,
        allowance: int,
    ) -> DetailedStageResult:
        nonlocal detailed_calls
        del prepared, allowance
        detailed_calls += 1
        raise AssertionError("cancelled global result reached detailed routing")

    solver = SequenceSolver(
        heights=(40,),
        problem_for_height=lambda height: PlacementProblem(
            sizes=((1, 1),),
            nets=((0, 0),),
            outline_height=height,
            area_lower_bound=1,
        ),
        adapters=StageAdapters(
            prepare=lambda height, decoded: (height, decoded),
            global_route=global_route,
            detailed_route=detailed_route,
            validate=lambda _placement: ValidationVerdict(True, ()),
        ),
        expansion_budget=budget,
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )

    with pytest.raises(NoValidLayout, match="routing was cancelled"):
        solver.search(max_stages=1)

    assert detailed_calls == 0
    assert budget.spent == 3
    assert len(feedback_seen) == 1
    assert not feedback_seen[0].net_weight
    assert not feedback_seen[0].cell_history


def test_deadline_empty_global_is_cancelled_without_budget_exhaustion() -> None:
    problem = PlacementProblem(((1, 1),), (), 1, 1)
    state = AnnealState.initial(1, 1)
    decoded = decode_sequence_pair(
        state.pair,
        state.gaps,
        problem.sizes,
        outline_height=problem.outline_height,
    )
    candidate = _ProductionCandidate(
        height=1,
        problem=problem,
        decoded=decoded,
        pack=_decoded_pack(1, decoded),
        prepared=None,
        preparation_error="deadline",
    )
    run = _production_run(
        two_stage_spec(),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )

    result = run.solver.adapters.global_route(
        candidate,
        FeedbackState.empty((1, 1)),
        0,
    )

    assert result.cancelled
    assert not result.exhausted_budget


def test_feedback_decays_once_then_adds_only_geometric_stage_evidence() -> None:
    geometric = DetailedStageResult(
        _routing(DetailedRouteStatus.STRANDED, geometric_failure=True), None
    )
    budget_only = DetailedStageResult(_routing(DetailedRouteStatus.BUDGET), None)
    fake = _FakeRouting(detailed_results=(geometric, budget_only, budget_only))
    with pytest.raises(NoValidLayout):
        _solver(fake, heights=(40,)).search(max_stages=3)
    net = NetId(0, 0, "item", NetRole.INTERNAL, 0)
    assert [state.net_weight.get(net, 0.0) for state in fake.feedback_seen] == [
        0.0,
        1.0,
        pytest.approx(0.85),
    ]


def test_deadline_returns_an_existing_exact_incumbent() -> None:
    exact = _placement(area=20, belt_tiles=4)
    checks = iter((False, True))
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),)
    )
    result = _solver(
        fake,
        heights=(40,),
        deadline_reached=lambda: next(checks),
    ).search(max_stages=5)
    assert result.placement is exact
    assert result.termination == "deadline"


def test_deadline_without_an_exact_incumbent_raises() -> None:
    with pytest.raises(NoValidLayout, match="deadline exhausted"):
        _solver(_FakeRouting(), deadline_reached=lambda: True).search(max_stages=5)


def test_deterministic_configuration_reproduces_stage_trace_and_derived_seeds() -> None:
    def run() -> tuple[SequenceSearchResult, list[int]]:
        exact = _placement(area=20, belt_tiles=4)
        fake = _FakeRouting(
            detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),)
        )
        result = _solver(fake, heights=(40, 60)).search(max_stages=5)
        return result, fake.stage_trace

    first, first_trace = run()
    second, second_trace = run()
    assert first_trace == second_trace
    assert first.stages == second.stages
    assert len({stage.seed for stage in first.stages}) > 1


def test_audit_layout_surface_uses_injected_solver_factory() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),)
    )
    calls: list[tuple[BuildSpec, float, bool, int, SequenceSolverConfig]] = []

    def factory(
        spec: BuildSpec,
        *,
        time_budget_s: float,
        power: bool,
        strip_len: int,
        config: SequenceSolverConfig,
    ) -> SequenceSolver[Prepared]:
        calls.append((spec, time_budget_s, power, strip_len, config))
        return _solver(fake, heights=(40,), config=config)

    config = SequenceSolverConfig(
        stages=1,
        moves_per_stage=1,
        restarts_per_height=1,
        global_elites=1,
    )
    layout = SequencePairLayout(
        solver_factory=factory,
        power=True,
        strip_len=7,
        config=config,
    )
    spec = two_stage_spec()
    assert layout.lay_out(spec, time_budget_s=2.5) is exact
    assert calls == [(spec, 2.5, True, 7, config)]


def _two_stage_variant_problem() -> tuple[
    BuildSpec,
    list[freeform_module.Strip],
    PlacementProblem,
]:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    instance_ids, variant_tables = _variant_search_inputs(
        spec,
        strips,
        strip_len=6,
    )
    sizes = tuple((variants[0].box_width, variants[0].box_height) for variants in variant_tables)
    return (
        spec,
        strips,
        PlacementProblem(
            sizes=sizes,
            nets=tuple(_nets_between(strips)),
            outline_height=20,
            area_lower_bound=sum(
                min(variant.box_width * variant.box_height for variant in variants)
                for variants in variant_tables
            ),
            instance_ids=instance_ids,
            variant_tables=variant_tables,
        ),
    )


def test_direct_targets_derive_geometry_from_both_selected_endpoint_variants() -> None:
    spec, strips, problem = _two_stage_variant_problem()
    default = (0,) * problem.size
    baseline = _selected_direct_targets(spec, strips, problem, default)
    assert len(baseline) == 1
    target = baseline[0]

    producer_selection = next(
        selection
        for variant in range(1, len(problem.variant_tables[target.producer]))
        if (
            selection := tuple(
                variant if strip == target.producer else 0 for strip in range(problem.size)
            )
        )
        and _selected_direct_targets(spec, strips, problem, selection)[0].producer_row
        != target.producer_row
    )
    consumer_selection = tuple(
        4 if strip == target.consumer else 0 for strip in range(problem.size)
    )

    producer_changed = _selected_direct_targets(spec, strips, problem, producer_selection)[0]
    consumer_plans = _selected_strips(strips, problem, consumer_selection)
    consumer_changed = _selected_direct_targets(spec, strips, problem, consumer_selection)[0]
    assert producer_changed.producer_row != target.producer_row
    assert producer_changed.consumer_row == target.consumer_row
    assert (
        consumer_plans[target.consumer].lane_plan
        != _selected_strips(strips, problem, default)[target.consumer].lane_plan
    )
    assert (
        consumer_changed
        == freeform_module._direct_alignment_targets(
            freeform_module._direct_net_candidates(consumer_plans, spec)
        )[0]
    )
    assert consumer_changed.producer_row == target.producer_row


def test_production_preparation_receives_the_complete_selected_physical_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    run = _production_run(
        spec,
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    height_state = run.solver._heights[0]
    problem = height_state.problem
    state = AnnealState.initial(problem.size, seed=7)
    state = apply_variant_move(problem, state, strip=0, variant=4)
    state = apply_variant_move(problem, state, strip=1, variant=4)
    decoded = decode_state(problem, state)
    captured: list[list[freeform_module.Strip]] = []

    def capture(
        spec: BuildSpec,
        selected: list[freeform_module.Strip],
        pack: _Pack,
        *,
        power: bool,
    ) -> _PreparedRoutingProblem:
        del spec, pack, power
        captured.append(selected)
        raise freeform_module._Unpowerable

    monkeypatch.setattr(sequence_solver_module, "_prepare_routing_problem", capture)
    candidate = run.solver.adapters.prepare(height_state.height, decoded)

    assert candidate.preparation_error == "unpowerable"
    assert len(captured) == 1
    selected = captured[0]
    assert selected == _selected_strips(
        plan_strips(spec, strip_len=6),
        problem,
        state.variant_indices,
    )
    assert candidate.decoded.variant_indices == state.variant_indices
    assert tuple(_box(strip) for strip in selected) == problem.selected_sizes(
        candidate.decoded.variant_indices
    )
    for strip, variant_index, physical in zip(
        selected,
        state.variant_indices,
        range(problem.size),
        strict=True,
    ):
        variant = problem.variant(physical, variant_index)
        assert (
            strip.yaw,
            strip.width,
            strip.height,
            strip.lane_plan,
            strip.attachment_plan,
        ) == (
            variant.yaw,
            variant.box_width,
            variant.box_height,
            variant.lane_plan,
            variant.attachment_plan,
        )


def test_selected_strips_rebuild_from_child_instance_ranges() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    instance_ids, variant_tables = _variant_search_inputs(
        spec,
        strips,
        strip_len=6,
    )
    family = next(
        family for family in generate_strip_families(spec) if family.total_machine_count > 1
    )
    target = next(
        index
        for index, instance in enumerate(instance_ids)
        if instance.family_id == family.family_id and instance.machine_count > 1
    )
    problem = PlacementProblem(
        sizes=tuple(_box(strip) for strip in strips),
        nets=tuple(_nets_between(strips)),
        outline_height=40,
        area_lower_bound=1,
        instance_ids=instance_ids,
        variant_tables=variant_tables,
    )
    state = AnnealState.initial(problem.size, seed=17)

    split = split_stage_boundary(problem, state, family, target)
    selected = _selected_strips(strips, split.problem, split.state.variant_indices)

    assert [strip.machines for strip in selected[target : target + 2]] == [
        split.problem.instance_ids[target].machine_count,
        split.problem.instance_ids[target + 1].machine_count,
    ]
    assert [strip.machine_start for strip in selected[target : target + 2]] == [
        split.problem.instance_ids[target].machine_start,
        split.problem.instance_ids[target + 1].machine_start,
    ]
    assert all(strip.family_id is not None for strip in selected)


def test_prepared_physical_nets_keep_stable_logical_family_edges() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    height = sum(_box(strip)[1] for strip in strips)
    prepared = _prepare_routing_problem(
        spec,
        strips,
        _greedy_pack(strips, height),
        power=False,
    )

    assert prepared.nets
    for net in prepared.nets:
        logical = net.net_id.logical_id
        assert logical is not None
        assert logical.source_family == (
            strips[net.net_id.source_strip].family_id
            if net.net_id.source_strip is not None
            else None
        )
        assert logical.destination_family == (
            strips[net.net_id.destination_strip].family_id
            if net.net_id.destination_strip is not None
            else None
        )


def test_production_stage_boundary_rebuilds_preparation_for_children() -> None:
    spec = two_stage_spec()
    run = _production_run(
        spec,
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    height_state = next(
        height
        for height in run.solver._heights
        if any(instance.machine_count > 1 for instance in height.problem.instance_ids)
    )
    problem = height_state.problem
    target = next(
        index for index, instance in enumerate(problem.instance_ids) if instance.machine_count > 1
    )
    state = height_state.restarts[0].anneal
    alternate_index = next(
        index
        for index, variant in enumerate(problem.variant_tables[target])
        if (variant.box_width, variant.box_height)
        != (
            problem.variant_tables[target][0].box_width,
            problem.variant_tables[target][0].box_height,
        )
    )
    alternate_state = apply_variant_move(
        problem,
        state,
        strip=target,
        variant=alternate_index,
    )
    result = DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(
            NetFailure(
                net_id=NetId(
                    target,
                    target,
                    "forced-split",
                    NetRole.INTERNAL,
                    0,
                ),
                kind=RouteFailureKind.CONGESTION_WALL,
                wall=((0, 0, 0),),
                blocking_nets=(),
                expansions=0,
            ),
        ),
        iterations=1,
        expansions=0,
    )
    transform = run.solver.stage_boundary_transform
    assert transform is not None

    transformed = transform(
        height_state.height,
        problem,
        state,
        height_state.feedback,
        result,
        2,
    )
    alternate = transform(
        height_state.height,
        problem,
        alternate_state,
        height_state.feedback,
        result,
        2,
    )

    assert transformed is not None
    assert alternate is not None
    assert transformed.problem == alternate.problem
    assert transformed.problem.size == problem.size + 1
    initial_strips = plan_strips(spec, strip_len=6)
    for update in (transformed, alternate):
        selected = _selected_strips(
            initial_strips,
            update.problem,
            update.state.variant_indices,
        )
        assert update.problem.selected_sizes(update.state.variant_indices) == tuple(
            _box(strip) for strip in selected
        )

    decoded = decode_state(alternate.problem, alternate.state)
    candidate = run.solver.adapters.prepare(height_state.height, decoded)
    assert candidate.problem == alternate.problem
    assert len(candidate.selected_strips) == alternate.problem.size
    assert tuple(
        (strip.family_id, strip.machine_start, strip.machines)
        for strip in candidate.selected_strips
    ) == tuple(
        (
            instance.family_id,
            instance.machine_start,
            instance.machine_count,
        )
        for instance in alternate.problem.instance_ids
    )


def test_rebuilt_net_order_keeps_matching_logical_family_weights() -> None:
    families = generate_strip_families(two_stage_spec())
    source = next(family for family in families if family.total_machine_count > 1)
    destination = next(family for family in families if family.family_id != source.family_id)
    source_variants = variants_for_count(source, 1)
    destination_variants = variants_for_count(destination, 1)
    second_destination_id = StripFamilyId("second-destination#0", 0)
    second_destination_variants = tuple(
        replace(
            variant,
            variant_id=replace(
                variant.variant_id,
                family_id=second_destination_id,
            ),
        )
        for variant in destination_variants
    )
    instance_ids = (
        StripInstanceId(source.family_id, 0, 1),
        StripInstanceId(source.family_id, 1, 1),
        StripInstanceId(destination.family_id, 0, 1),
        StripInstanceId(second_destination_id, 0, 1),
    )
    tables = (
        source_variants,
        source_variants,
        destination_variants,
        second_destination_variants,
    )
    original_nets = ((0, 2), (1, 2), (0, 3), (1, 3))
    problem = PlacementProblem(
        sizes=tuple((variants[0].box_width, variants[0].box_height) for variants in tables),
        nets=original_nets,
        outline_height=40,
        area_lower_bound=1,
        instance_ids=instance_ids,
        variant_tables=tables,
        logical_net_families=tuple(
            (
                instance_ids[source_index].family_id,
                instance_ids[destination_index].family_id,
            )
            for source_index, destination_index in original_nets
        ),
    )
    sorted_nets = tuple(sorted(original_nets))

    rebuilt = _rebuild_stage_problem_nets(problem, sorted_nets)

    assert rebuilt.nets == sorted_nets
    assert rebuilt.logical_net_families == tuple(
        (
            rebuilt.instance_ids[source_index].family_id,
            rebuilt.instance_ids[destination_index].family_id,
        )
        for source_index, destination_index in sorted_nets
    )
    weighted_edge = LogicalNetId(
        source.family_id,
        second_destination_id,
        "split-product",
        NetRole.INTERNAL,
    )
    context = feedback_cost_context(
        FeedbackState(
            outline=(40, 40),
            net_weight={},
            cell_history={},
            logical_net_weight={weighted_edge: 2.0},
        ),
        rebuilt,
    )
    assert context.net_weights == (1.0, 3.0, 1.0, 3.0)


def test_feedback_stagnation_rebuilds_the_next_fixed_cardinality_stage() -> None:
    family = next(
        family
        for family in generate_strip_families(two_stage_spec())
        if family.total_machine_count > 1
    )
    (instance,) = partition_strip_family(
        family,
        max_machine_count=family.total_machine_count,
    )
    variants = variants_for_count(family, family.total_machine_count)
    problem = PlacementProblem(
        sizes=((variants[0].box_width, variants[0].box_height),),
        nets=((0, 0),),
        outline_height=40,
        area_lower_bound=1,
        instance_ids=(instance.instance_id,),
        variant_tables=(variants,),
    )
    prepared_sizes: list[int] = []
    transformed_stagnation: list[int] = []

    def prepare(_height: int, decoded: DecodedPlacement) -> DecodedPlacement:
        prepared_sizes.append(len(decoded.x))
        return decoded

    failure = _routing(
        DetailedRouteStatus.STRANDED,
        geometric_failure=True,
    )

    def transform(
        _height: int,
        stage_problem: PlacementProblem,
        stage_state: AnnealState,
        _feedback: FeedbackState,
        result: DetailedRouteResult,
        stagnation: int,
    ) -> StageBoundaryUpdate | None:
        transformed_stagnation.append(stagnation)
        target = select_split_candidate(
            result,
            stage_problem.instance_ids,
            stagnation=stagnation,
            split_after=2,
        )
        return (
            None
            if target is None
            else split_stage_boundary(stage_problem, stage_state, family, target)
        )

    solver = SequenceSolver(
        heights=(40,),
        problem_for_height=lambda _height: problem,
        adapters=StageAdapters(
            prepare=prepare,
            global_route=lambda _prepared, _feedback, _allowance: _global(),
            detailed_route=lambda _prepared, _allowance: DetailedStageResult(
                failure,
                None,
            ),
            validate=lambda _placement: ValidationVerdict(False, ("unreachable",)),
        ),
        expansion_budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=3,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        stage_boundary_transform=transform,
    )

    with pytest.raises(NoValidLayout):
        solver.search(max_stages=3)
    assert transformed_stagnation == [1, 2, 1]
    assert prepared_sizes == [1, 1, 2]
    assert solver._heights[0].problem.size == 2
    assert solver._heights[0].restarts[0].anneal.base_seed == solver._heights[0].restarts[0].seed
    assert sum(stage.split_count for stage in solver._stage_stats) == 1
    assert sum(stage.merge_count for stage in solver._stage_stats) == 0
    assert solver._heights[0].restarts[0].anneal.stage_index == 3


@pytest.mark.parametrize("power", [False, True])
def test_sequence_backend_returns_only_certified_placements(power: bool) -> None:
    spec = two_stage_spec()
    placement = SequencePairLayout(
        power=power,
        config=SequenceSolverConfig.test(),
    ).lay_out(spec, time_budget_s=2.0)

    assert not validate.certify(placement, spec, expect_power=power).errors
    assert cast(object, placement.stats["backend"]) == "sequence-pair"
    assert placement.stats["detailed_routes"] >= 1.0
    assert placement.stats["direct_candidates"] == 1.0
    assert 0.0 <= placement.stats["direct_inserts"] <= 1.0
    assert placement.stats["power"] == float(power)
    assert (placement.stats["towers"] > 0.0) is power
    assert {
        "seeds",
        "seed",
        "accelerator",
        "heights",
        "restarts",
        "stages",
        "moves",
        "accepted_moves",
        "decoded_candidates",
        "global_routes",
        "detailed_routes",
        "best_overflow",
        "best_stranded",
        "lns_invocations",
        "lns_total_size",
        "feedback_nets",
        "feedback_cells",
        "variant_moves",
        "pose_count",
        "pose_yaw_0",
        "pose_yaw_90",
        "pose_yaw_180",
        "pose_yaw_270",
        "split_count",
        "merge_count",
        "pose_feasibility_rejects",
        "elevated_coater_routes",
        "lns_max_size",
        "feedback_decays",
        "placement_time_s",
        "preparation_time_s",
        "global_route_time_s",
        "planning_time_s",
        "detailed_route_time_s",
        "validation_time_s",
        "compilation_time_s",
        "total_time_s",
        "global_expansions",
        "detailed_expansions",
        "expansions",
        "expansion_allowance",
        "final_reserved",
        "cache_hits",
        "direct_candidates",
        "direct_inserts",
        "area",
        "belt_tiles",
        "power",
        "termination_cause",
        "termination",
        "validation_clean",
        "validation_status",
    } <= placement.stats.keys()


def test_production_threads_global_rounds_and_hard_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = route_global
    calls: list[tuple[int | None, bool]] = []

    def recording_global(
        prepared: object,
        feedback: FeedbackState,
        allowance: int,
        *,
        max_rounds: int | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> GlobalRouteResult:
        calls.append((max_rounds, cancelled is not None))
        return original(
            prepared,  # type: ignore[arg-type]
            feedback,
            allowance,
            max_rounds=max_rounds or 5,
            cancelled=cancelled,
        )

    monkeypatch.setattr(sequence_solver_module, "route_global", recording_global)
    config = SequenceSolverConfig(
        stages=1,
        moves_per_stage=1,
        restarts_per_height=1,
        global_elites=1,
        global_rounds=1,
    )

    SequencePairLayout(power=False, config=config).lay_out(
        two_stage_spec(),
        time_budget_s=2.0,
    )

    assert calls
    assert set(calls) == {(1, True)}


def test_detailed_candidate_reuses_prepared_problem_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, sum(_box(strip)[1] for strip in strips))
    prepared = _prepare_routing_problem(spec, strips, pack, power=False)
    original = _build_prepared
    preparation_calls = 0

    def unexpected_prepare(*args: object, **kwargs: object) -> object:
        nonlocal preparation_calls
        del args, kwargs
        preparation_calls += 1
        return prepared

    monkeypatch.setattr(
        freeform_module,
        "_prepare_routing_problem",
        unexpected_prepare,
    )
    seen: list[object] = []

    def recording_build(
        build_spec: BuildSpec,
        build_strips: list[object],
        build_prepared: object,
        **kwargs: object,
    ) -> object:
        seen.append(build_prepared)
        return original(
            build_spec,
            build_strips,  # type: ignore[arg-type]
            build_prepared,  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(
        sequence_solver_module,
        "_build_prepared",
        recording_build,
    )
    result = _route_detailed_candidate(
        spec,
        strips,
        prepared,
        power=False,
        deadline=None,
        allowance=100_000,
    )

    assert seen == [prepared]
    assert result.routing.status is DetailedRouteStatus.ROUTED
    assert preparation_calls == 0


def test_post_route_power_failure_charges_shared_spend_and_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, sum(_box(strip)[1] for strip in strips))
    prepared = _prepare_routing_problem(spec, strips, pack, power=True)

    def unpowerable_after_route(*args: object, **kwargs: object) -> object:
        del args
        attempt_budget = kwargs["budget"]
        assert isinstance(attempt_budget, dict)
        left = attempt_budget["left"]
        assert isinstance(left, int)
        attempt_budget["left"] = left - 7
        raise _Unpowerable

    monkeypatch.setattr(
        sequence_solver_module,
        "_build_prepared",
        unpowerable_after_route,
    )
    detailed_results: list[DetailedStageResult] = []

    def detailed_route(
        candidate: _PreparedRoutingProblem,
        allowance: int,
    ) -> DetailedStageResult:
        result = _route_detailed_candidate(
            spec,
            strips,
            candidate,
            power=True,
            deadline=None,
            allowance=allowance,
        )
        detailed_results.append(result)
        return result

    ledger = ExpansionBudget(100)
    solver = SequenceSolver(
        heights=(1,),
        problem_for_height=lambda _height: PlacementProblem(
            ((1, 1),),
            (),
            1,
            1,
        ),
        adapters=StageAdapters(
            prepare=lambda _height, _decoded: prepared,
            global_route=lambda _prepared, _feedback, _allowance: _global(),
            detailed_route=detailed_route,
            validate=lambda _placement: ValidationVerdict(True, ()),
        ),
        expansion_budget=ledger,
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )

    with pytest.raises(NoValidLayout) as exc:
        solver.search(max_stages=1)

    assert exc.value.reason == "no scheduled stage produced an exact layout"
    assert len(detailed_results) == 1
    result = detailed_results[0]
    assert result.routing.status is DetailedRouteStatus.UNPOWERABLE
    assert result.routing.expansions == 7
    assert result.routing.failed_count == 0
    assert result.placement is None
    assert ledger.spent == 7


def test_powered_one_net_miss_feeds_lns_or_refuses_honestly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quantum = entry("quantum-chip")
    spec = build_candidates(
        load_vendored(),
        parse_url(quantum.url),
        count=1,
    ).candidates[0]
    strips = plan_strips(spec, strip_len=6)
    frozen_at = (
        (1, 0),
        (1, 8),
        (1, 15),
        (1, 22),
        (1, 29),
        (1, 36),
        (1, 42),
        (1, 51),
        (1, 57),
        (1, 63),
        (1, 69),
        (1, 76),
        (1, 86),
        (1, 93),
        (1, 100),
        (1, 107),
        (1, 119),
        (58, 0),
        (58, 12),
        (58, 24),
        (58, 36),
        (58, 48),
        (58, 60),
        (58, 72),
        (58, 83),
        (58, 94),
        (58, 105),
        (58, 116),
        (78, 0),
        (78, 11),
        (78, 22),
        (78, 33),
        (78, 42),
        (78, 49),
        (79, 56),
        (78, 66),
        (78, 73),
        (78, 81),
        (78, 89),
        (78, 96),
    )
    assert len(strips) == len(frozen_at) == 40
    frozen = _Pack(
        at=dict(enumerate(frozen_at)),
        width=134,
        height=136,
        status="frozen-powered-one-net-miss",
    )
    frozen_prepared = _prepare_routing_problem(
        spec,
        strips,
        frozen,
        power=True,
    )
    sizes = tuple(_box(strip) for strip in strips)
    problem = PlacementProblem(
        sizes=sizes,
        nets=tuple(_nets_between(strips)),
        outline_height=frozen.height,
        area_lower_bound=sum(width * height for width, height in sizes),
    )
    east = [0] * len(strips)
    east[11] = 1
    selected_pair = SequencePair(
        positive=tuple(range(len(strips))),
        negative=(
            *range(16, -1, -1),
            *range(27, 16, -1),
            *range(39, 27, -1),
        ),
    )
    selected_holder: list[AnnealState] = []
    anneal_inputs: list[AnnealState] = []

    def incumbent(state: AnnealState) -> AnnealIncumbent:
        decoded = decode_sequence_pair(
            state.pair,
            state.gaps,
            problem.sizes,
            outline_height=problem.outline_height,
        )
        return AnnealIncumbent(
            state=state,
            decoded=decoded,
            energy=SearchEnergy(0, 0.0),
            key=PlacementKey(
                x=decoded.x,
                y=decoded.y,
                dimensions=problem.sizes,
                east_gaps=state.gaps.east,
                north_gaps=state.gaps.north,
            ),
        )

    def frozen_anneal_stage(
        stage_problem: PlacementProblem,
        state: AnnealState,
        config: object,
        context: PlacementCostContext | None = None,
    ) -> AnnealStageResult:
        del stage_problem, config, context
        anneal_inputs.append(state)
        if not selected_holder:
            selected = AnnealState(
                selected_pair,
                GapProfile(tuple(east), (0,) * len(strips)),
                base_seed=state.base_seed,
            )
            selected_holder.append(selected)
            elite = incumbent(selected)
            return AnnealStageResult(
                final_state=AnnealState(
                    selected.pair,
                    selected.gaps,
                    selected.base_seed,
                    stage_index=1,
                ),
                incumbent=elite,
                accepted_moves=0,
                elites=(elite,),
            )
        elite = incumbent(state)
        return AnnealStageResult(
            final_state=AnnealState(
                state.pair,
                state.gaps,
                state.base_seed,
                stage_index=state.stage_index + 1,
            ),
            incumbent=elite,
            accepted_moves=0,
            elites=(elite,),
        )

    monkeypatch.setattr(
        sequence_solver_module,
        "anneal_stage",
        frozen_anneal_stage,
    )
    prepared_calls = 0

    def prepare(height: int, decoded: DecodedPlacement) -> _PreparedRoutingProblem:
        nonlocal prepared_calls
        prepared_calls += 1
        if prepared_calls == 1:
            assert decoded == incumbent(selected_holder[0]).decoded
            return frozen_prepared
        return _prepare_routing_problem(
            spec,
            strips,
            _decoded_pack(height, decoded),
            power=True,
        )

    feedback_seen: list[FeedbackState] = []

    def global_stage(
        prepared: _PreparedRoutingProblem,
        feedback: FeedbackState,
        allowance: int,
    ) -> GlobalRouteResult:
        feedback_seen.append(feedback)
        return route_global(
            prepared,
            feedback,
            allowance,
            max_rounds=1,
        )

    detailed_results: list[DetailedStageResult] = []

    def detailed_stage(
        prepared: _PreparedRoutingProblem,
        allowance: int,
    ) -> DetailedStageResult:
        result = _route_detailed_candidate(
            spec,
            strips,
            prepared,
            power=True,
            deadline=None,
            allowance=allowance,
        )
        detailed_results.append(result)
        return result

    def certify(placement: Placement) -> ValidationVerdict:
        report = validate.certify(placement, spec, expect_power=True)
        failures = tuple(sorted({finding.check for finding in report.errors}))
        return ValidationVerdict(not failures, failures)

    solver = SequenceSolver(
        heights=(frozen.height,),
        problem_for_height=lambda _height: problem,
        adapters=StageAdapters(
            prepare=prepare,
            global_route=global_stage,
            detailed_route=detailed_stage,
            validate=certify,
        ),
        expansion_budget=ExpansionBudget(8_000_000),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
            global_rounds=1,
        ),
    )
    with contextlib.suppress(NoValidLayout):
        solver.search(max_stages=2)

    first = detailed_results[0]
    assert first.routing.status is DetailedRouteStatus.STRANDED
    assert first.routing.failed_count == 1
    assert first.placement is None
    failure = first.routing.failures[0]
    assert failure.net_id in feedback_seen[1].net_weight

    selected = selected_holder[0]
    selected_decoded = incumbent(selected).decoded
    neighbourhood = select_lns_neighbourhood(
        first.routing,
        selected.pair,
        selected.gaps,
        problem,
        selected_decoded,
    )
    expected = {
        endpoint
        for net_id in (failure.net_id, *failure.blocking_nets)
        for endpoint in (net_id.source_strip, net_id.destination_strip)
        if endpoint is not None
    }
    assert expected <= neighbourhood
    repaired = repair_neighbourhood(
        selected.pair,
        selected.gaps,
        neighbourhood,
        seed=derive_stage_seed(selected.base_seed, 1),
    )
    assert anneal_inputs[1] == AnnealState(
        repaired.pair,
        repaired.gaps,
        selected.base_seed,
        stage_index=1,
    )

    second = detailed_results[1]
    if second.placement is None:
        assert second.routing.status is not DetailedRouteStatus.ROUTED
    else:
        assert second.routing.status is DetailedRouteStatus.ROUTED
        assert not validate.certify(
            second.placement,
            spec,
            expect_power=True,
        ).errors


def test_lns_continues_from_the_proxy_selected_elite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = PlacementProblem(
        sizes=((1, 1),) * 4,
        nets=((0, 1),),
        outline_height=4,
        area_lower_bound=4,
    )
    anneal_inputs: list[AnnealState] = []
    selected_states: list[AnnealState] = []

    def incumbent(state: AnnealState, scalar: float) -> AnnealIncumbent:
        decoded = decode_sequence_pair(
            state.pair,
            state.gaps,
            problem.sizes,
            outline_height=problem.outline_height,
        )
        return AnnealIncumbent(
            state=state,
            decoded=decoded,
            energy=SearchEnergy(0, scalar),
            key=PlacementKey(
                x=decoded.x,
                y=decoded.y,
                dimensions=problem.sizes,
                east_gaps=state.gaps.east,
                north_gaps=state.gaps.north,
            ),
        )

    def fake_anneal_stage(
        stage_problem: PlacementProblem,
        state: AnnealState,
        config: object,
        context: PlacementCostContext | None = None,
    ) -> AnnealStageResult:
        del stage_problem, config, context
        anneal_inputs.append(state)
        if len(anneal_inputs) == 1:
            selected = AnnealState(
                pair=SequencePair((0, 1, 2, 3), (0, 1, 2, 3)),
                gaps=GapProfile((1, 0, 0, 0), (0, 0, 0, 0)),
                base_seed=state.base_seed,
                stage_index=state.stage_index,
            )
            final = AnnealState(
                pair=SequencePair((2, 0, 3, 1), (1, 0, 2, 3)),
                gaps=GapProfile.zero(4),
                base_seed=state.base_seed,
                stage_index=state.stage_index + 1,
            )
            selected_states.append(selected)
            final_elite = incumbent(final, 0.0)
            selected_elite = incumbent(selected, 1.0)
            return AnnealStageResult(
                final_state=final,
                incumbent=final_elite,
                accepted_moves=1,
                elites=(final_elite, selected_elite),
            )
        only = incumbent(state, 0.0)
        return AnnealStageResult(
            final_state=AnnealState(
                pair=state.pair,
                gaps=state.gaps,
                base_seed=state.base_seed,
                stage_index=state.stage_index + 1,
            ),
            incumbent=only,
            accepted_moves=0,
            elites=(only,),
        )

    monkeypatch.setattr(sequence_solver_module, "anneal_stage", fake_anneal_stage)
    failure = NetFailure(
        net_id=NetId(0, None, "item", NetRole.INTERNAL, 0),
        kind=RouteFailureKind.CONGESTION_WALL,
        wall=((0, 0, 0),),
        blocking_nets=(),
        expansions=0,
    )
    detailed_calls = 0

    def global_route(
        decoded: DecodedPlacement,
        feedback: FeedbackState,
        allowance: int,
    ) -> GlobalRouteResult:
        del feedback, allowance
        selected = selected_states[0]
        selected_decoded = decode_sequence_pair(
            selected.pair,
            selected.gaps,
            problem.sizes,
            outline_height=problem.outline_height,
        )
        return _global(overflow=0 if decoded == selected_decoded else 10)

    def detailed_route(decoded: DecodedPlacement, allowance: int) -> DetailedStageResult:
        nonlocal detailed_calls
        del decoded, allowance
        detailed_calls += 1
        if detailed_calls == 1:
            return DetailedStageResult(
                DetailedRouteResult(
                    status=DetailedRouteStatus.STRANDED,
                    routed=(),
                    failures=(failure,),
                    iterations=1,
                    expansions=0,
                ),
                None,
            )
        return DetailedStageResult(_routing(DetailedRouteStatus.BUDGET), None)

    solver = SequenceSolver(
        heights=(4,),
        problem_for_height=lambda _height: problem,
        adapters=StageAdapters(
            prepare=lambda _height, decoded: decoded,
            global_route=global_route,
            detailed_route=detailed_route,
            validate=lambda _placement: ValidationVerdict(False, ("unreachable",)),
        ),
        expansion_budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=2,
        ),
    )
    with pytest.raises(NoValidLayout):
        solver.search(max_stages=2)

    selected = selected_states[0]
    selected_decoded = decode_sequence_pair(
        selected.pair,
        selected.gaps,
        problem.sizes,
        outline_height=problem.outline_height,
    )
    neighbourhood = select_lns_neighbourhood(
        DetailedRouteResult(
            status=DetailedRouteStatus.STRANDED,
            routed=(),
            failures=(failure,),
            iterations=1,
            expansions=0,
        ),
        selected.pair,
        selected.gaps,
        problem,
        selected_decoded,
    )
    repaired = repair_neighbourhood(
        selected.pair,
        selected.gaps,
        neighbourhood,
        seed=derive_stage_seed(anneal_inputs[0].base_seed, 1),
    )
    assert anneal_inputs[1] == AnnealState(
        pair=repaired.pair,
        gaps=repaired.gaps,
        base_seed=anneal_inputs[0].base_seed,
        stage_index=1,
    )


def _single_real_machine_spec(
    *,
    recipe: str,
    machine: str,
    inputs: tuple[str, ...],
    outputs: tuple[str, ...],
) -> BuildSpec:
    one = Fraction(1)
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id=recipe,
                machine_item_id=machine,
                count=1,
                inputs_per_machine={item: one for item in inputs},
                outputs_per_machine={item: one for item in outputs},
            ),
        ),
        external_inputs={item: one for item in inputs},
        outputs={item: one for item in outputs},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=Fraction(30),
        label=f"sequence-{machine}",
    )


def test_refinery_closed_loop_routes_the_selected_rotated_pose() -> None:
    spec = _single_real_machine_spec(
        recipe="plasma-refining",
        machine="oil-refinery",
        inputs=("crude-oil",),
        outputs=("refined-oil", "hydrogen"),
    )

    placement = SequencePairLayout(config=SequenceSolverConfig.test()).lay_out(
        spec,
        time_budget_s=2.0,
    )

    refinery = next(building for building in placement.buildings if building.item_id == 2308)
    assert refinery.yaw in {90.0, 270.0}
    assert not validate.certify(placement, spec, expect_power=False).errors
    assert placement.stats["detailed_routes"] >= 1.0
    assert placement.stats["pose_count"] == 1.0
    assert (placement.stats["pose_yaw_90"] + placement.stats["pose_yaw_270"]) == 1.0
    assert placement.stats["pose_feasibility_rejects"] >= 1.0


def test_chemical_closed_loop_emits_exact_inner_anchor_sorters() -> None:
    spec = _single_real_machine_spec(
        recipe="graphene-advanced",
        machine="chemical-plant",
        inputs=("fire-ice",),
        outputs=("graphene", "hydrogen"),
    )

    placement = SequencePairLayout(config=SequenceSolverConfig.test()).lay_out(
        spec,
        time_budget_s=2.0,
    )

    machine_index, machine = next(
        (index, building)
        for index, building in enumerate(placement.buildings)
        if building.item_id == 2309
    )
    machine_cells: list[tuple[int, int]] = []
    for sorter in (
        building
        for building in placement.buildings
        if catalog.is_sorter(building.item_id)
        and (building.output_obj == machine_index or building.input_obj == machine_index)
    ):
        assert sorter.x2 is not None and sorter.y2 is not None
        if sorter.output_obj == machine_index:
            far = (sorter.x, sorter.y)
            machine_cell = (sorter.x2, sorter.y2)
            slot = sorter.output_to_slot
        else:
            far = (sorter.x2, sorter.y2)
            machine_cell = (sorter.x, sorter.y)
            slot = sorter.input_from_slot
        attachment = slots.attachment(machine, far)
        assert attachment is not None
        assert attachment.cell == machine_cell
        assert attachment.slot == slot
        assert attachment.span == max(
            abs(sorter.x - sorter.x2),
            abs(sorter.y - sorter.y2),
        )
        machine_cells.append(machine_cell)

    assert machine_cells
    assert any(
        machine.x < x < machine.x + machine.width - 1
        and machine.y < y < machine.y + machine.height - 1
        for x, y in machine_cells
    )
    assert not validate.certify(placement, spec, expect_power=False).errors
    assert placement.stats["pose_count"] == 1.0


def test_proliferated_closed_loop_routes_elevated_supply_without_coater_sorter() -> None:
    spec = proliferated_spec()

    placement = SequencePairLayout(config=SequenceSolverConfig.test()).lay_out(
        spec,
        time_budget_s=2.0,
    )

    coaters = {
        index: building
        for index, building in enumerate(placement.buildings)
        if building.item_id == catalog.SPRAY_COATER_ID
    }
    assert coaters
    assert all(
        building.output_obj not in coaters and building.input_obj not in coaters
        for building in placement.buildings
        if catalog.is_sorter(building.item_id)
    )
    for coater in coaters.values():
        target = slots.addon_supply_cell(
            coater.item_id,
            x=coater.x,
            y=coater.y,
            z=coater.z,
            yaw=coater.yaw,
            area=1,
        )
        assert any(
            (building.x, building.y, building.z) == (target[0], target[1], Fraction(target[2]))
            and building.carries_item in spec.external_inputs
            for building in placement.buildings
            if catalog.is_belt(building.item_id)
        )
    assert not validate.certify(placement, spec, expect_power=False).errors
    assert placement.stats["elevated_coater_routes"] == float(len(coaters))


def test_impossible_elevated_coater_route_refuses_without_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = proliferated_spec()
    original_prepare = _prepare_routing_problem
    original_detailed = sequence_solver_module._route_detailed_candidate
    detailed_results: list[DetailedStageResult] = []

    def blocked_prepare(*args: object, **kwargs: object) -> _PreparedRoutingProblem:
        prepared = original_prepare(*args, **kwargs)  # type: ignore[arg-type]
        blocked = dict(prepared.blocked)
        for port in prepared.coater_supply_ports:
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                blocked[(port.x + dx, port.y + dy, port.z)] = -1
        return replace(prepared, blocked=tuple(sorted(blocked.items())))

    def recording_detailed(*args: object, **kwargs: object) -> DetailedStageResult:
        result = original_detailed(*args, **kwargs)  # type: ignore[arg-type]
        detailed_results.append(result)
        return result

    monkeypatch.setattr(sequence_solver_module, "_prepare_routing_problem", blocked_prepare)
    monkeypatch.setattr(sequence_solver_module, "_route_detailed_candidate", recording_detailed)

    with pytest.raises(NoValidLayout):
        SequencePairLayout(config=SequenceSolverConfig.test()).lay_out(
            spec,
            time_budget_s=2.0,
        )

    assert detailed_results
    assert all(result.placement is None for result in detailed_results)
    assert any(
        failure.net_id.role is NetRole.PROLIFERATOR
        for result in detailed_results
        for failure in result.routing.failures
    )


def test_broad_feedback_continues_from_routed_elite_variant_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _spec, _strips, problem = _two_stage_variant_problem()
    anneal_inputs: list[AnnealState] = []
    routed_states: list[AnnealState] = []

    def incumbent(state: AnnealState, scalar: float) -> AnnealIncumbent:
        decoded = decode_state(problem, state)
        sizes = problem.selected_sizes(state.variant_indices)
        return AnnealIncumbent(
            state=state,
            decoded=decoded,
            energy=SearchEnergy(0, scalar),
            key=PlacementKey(
                x=decoded.x,
                y=decoded.y,
                dimensions=sizes,
                east_gaps=state.gaps.east,
                north_gaps=state.gaps.north,
                instance_ids=problem.instance_ids,
                variant_ids=problem.selected_variant_ids(state.variant_indices),
            ),
        )

    def fake_anneal_stage(
        stage_problem: PlacementProblem,
        state: AnnealState,
        config: object,
        context: PlacementCostContext | None = None,
        *,
        direct_targets_for_state: object = None,
    ) -> AnnealStageResult:
        del stage_problem, config, context, direct_targets_for_state
        anneal_inputs.append(state)
        if len(anneal_inputs) == 1:
            selected = replace(state, variant_indices=(1, 0))
            final = replace(state, stage_index=state.stage_index + 1)
            routed_states.append(selected)
            return AnnealStageResult(
                final_state=final,
                incumbent=incumbent(final, 0.0),
                accepted_moves=1,
                elites=(incumbent(final, 0.0), incumbent(selected, 1.0)),
            )
        next_state = replace(state, stage_index=state.stage_index + 1)
        only = incumbent(state, 0.0)
        return AnnealStageResult(next_state, only, 0, (only,))

    monkeypatch.setattr(sequence_solver_module, "anneal_stage", fake_anneal_stage)

    failures = tuple(
        NetFailure(
            net_id=NetId(0, 1, f"item-{index}", NetRole.INTERNAL, index),
            kind=RouteFailureKind.CONGESTION_WALL,
            wall=((index, 0, 0),),
            blocking_nets=(),
            expansions=0,
        )
        for index in range(4)
    )
    detailed_calls = 0

    def global_route(
        decoded: DecodedPlacement,
        feedback: FeedbackState,
        allowance: int,
    ) -> GlobalRouteResult:
        del feedback, allowance
        routed = decode_state(problem, routed_states[0])
        return _global(overflow=0 if decoded == routed else 10)

    def detailed_route(
        decoded: DecodedPlacement,
        allowance: int,
    ) -> DetailedStageResult:
        nonlocal detailed_calls
        del decoded, allowance
        detailed_calls += 1
        if detailed_calls == 1:
            return DetailedStageResult(
                DetailedRouteResult(
                    status=DetailedRouteStatus.STRANDED,
                    routed=(),
                    failures=failures,
                    iterations=1,
                    expansions=0,
                ),
                None,
            )
        return DetailedStageResult(_routing(DetailedRouteStatus.BUDGET), None)

    solver = SequenceSolver(
        heights=(problem.outline_height,),
        problem_for_height=lambda _height: problem,
        adapters=StageAdapters(
            prepare=lambda _height, decoded: decoded,
            global_route=global_route,
            detailed_route=detailed_route,
            validate=lambda _placement: ValidationVerdict(False, ("unreachable",)),
        ),
        expansion_budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=2,
        ),
    )

    with pytest.raises(NoValidLayout):
        solver.search(max_stages=2)

    assert anneal_inputs[1] == replace(routed_states[0], stage_index=1)
    first = solver._stage_stats[0]
    assert first.variant_moves == 1
    assert first.selected_instance_ids == problem.instance_ids
    assert first.selected_variant_ids == problem.selected_variant_ids((1, 0))
    assert first.selected_pose_yaws == tuple(
        problem.variant(strip, variant).yaw for strip, variant in enumerate((1, 0))
    )
