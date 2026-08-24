from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import pytest

import flab2bp.layout.freeform as freeform_module
import flab2bp.layout.sequence_solver as sequence_solver_module
from flab2bp.bench.corpus import entry
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout import validate
from flab2bp.layout.base import NoValidLayout, PlacedBuilding, Placement
from flab2bp.layout.freeform import (
    _box,
    _build_prepared,
    _greedy_pack,
    _nets_between,
    _Pack,
    _prepare_routing_problem,
    _PreparedRoutingProblem,
    plan_strips,
)
from flab2bp.layout.global_router import GlobalRouteResult, route_global
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
from flab2bp.layout.sequence_pair import (
    AnnealIncumbent,
    AnnealStageResult,
    AnnealState,
    DecodedPlacement,
    GapProfile,
    PlacementCostContext,
    PlacementKey,
    PlacementProblem,
    SearchEnergy,
    SequencePair,
    decode_sequence_pair,
    derive_stage_seed,
    repair_neighbourhood,
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
    _route_detailed_candidate,
)
from flab2bp.rates.candidates import build_candidates
from flab2bp.spec import BuildSpec
from tests.layout.test_freeform import two_stage_spec

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


def _global(*, overflow: int = 0, expansions: int = 0) -> GlobalRouteResult:
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
        detailed_results=(
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), invalid),
        )
    )
    with pytest.raises(NoValidLayout):
        _solver(fake, heights=(40,)).search(max_stages=1)


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
            detailed_results=(
                DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),
            )
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

    def prepare(
        height: int, decoded: DecodedPlacement
    ) -> _PreparedRoutingProblem:
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

    def detailed_route(
        decoded: DecodedPlacement, allowance: int
    ) -> DetailedStageResult:
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
