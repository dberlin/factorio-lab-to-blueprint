from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Never, TypedDict

import pytest

import flab2bp.layout.freeform as freeform_module
import flab2bp.layout.sequence_solver as sequence_solver_module
from flab2bp.dsp import catalog, rules
from flab2bp.layout import finalize, slots, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import (
    AreaFrame,
    NoValidLayout,
    PlacedBuilding,
    Placement,
    PlacementCompletion,
)
from flab2bp.layout.compact_seed import (
    CompactSeedConfig,
    CompactSeedDiagnostics,
    CompactSeedResult,
    CompactSeedStatus,
    CompactTopologyCandidate,
    PairwiseRelationSignature,
    VariantDirectInsertTarget,
)
from flab2bp.layout.freeform import (
    _box,
    _greedy_pack,
    _nets_between,
    _prepare_routing_problem,
    plan_strips,
)
from flab2bp.layout.global_router import GlobalRouteResult
from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
    select_split_candidate,
)
from flab2bp.layout.sequence_pair import (
    AnnealIncumbent,
    AnnealState,
    DecodedPlacement,
    DirectInsertTarget,
    EliteCategory,
    GapProfile,
    PlacementKey,
    PlacementProblem,
    SequencePair,
    StageBoundaryUpdate,
    TaggedAnnealIncumbent,
    apply_variant_move,
    build_elite_archive,
    decode_sequence_pair,
    decode_state,
    enable_variant_stage_boundary,
    split_stage_boundary,
)
from flab2bp.layout.sequence_solver import (
    DetailedStageResult,
    ExpansionBudget,
    SequencePairLayout,
    SequenceSolver,
    SequenceSolverConfig,
    StageAdapters,
    ValidationVerdict,
    _decoded_pack,
    _placement_nets,
    _pose_stage_boundary_update,
    _production_run,
    _ProductionCandidate,
    _selected_direct_targets,
    _selected_strips,
    _variant_search_inputs,
)
from flab2bp.layout.strip_variants import (
    ProjectionPitchRequirement,
    StripInstanceId,
    StripVariant,
    generate_strip_families,
    partition_strip_family,
    projection_pitch_requirement,
    variant_with_minimum_pitch,
    variants_for_count,
)
from flab2bp.spec import BuildSpec, MachineGroup
from tests.layout.test_freeform import (
    band_120_control_spec,
    plastic_spec,
    projected_chemical_plant_spec,
    proliferated_spec,
    ray_receiver_spec,
    spray_domain_spec,
    two_stage_spec,
)

Prepared = tuple[int, DecodedPlacement]


class _ProductionRunCapture(TypedDict, total=False):
    compact_seed_attempt: int | None
    compact_seed_config: CompactSeedConfig | None
    power: bool


class _CompactSeedCapture(TypedDict, total=False):
    called_at: float
    config: CompactSeedConfig | None
    direct_eligibility: tuple[VariantDirectInsertTarget, ...]
    absolute_deadline: float | None


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


def test_sequence_pair_preserves_mixed_spray_domain_logical_nets() -> None:
    spec = spray_domain_spec(clean=True, sprayed=True)
    strips = plan_strips(spec, strip_len=6)

    iron_nets = [
        (endpoints, logical)
        for endpoints, logical in _placement_nets(strips)
        if logical.item == "iron-ingot"
    ]

    assert {logical.cargo_domain.value for _endpoints, logical in iron_nets} == {
        "requires-spray",
        "unsprayed",
    }
    for (_source, destination), logical in iron_nets:
        assert strips[destination].cargo_domain is logical.cargo_domain


def _routing(
    status: DetailedRouteStatus,
    *,
    expansions: int = 0,
    geometric_failure: bool = False,
    failure_kind: RouteFailureKind | None = None,
    source: tuple[int, int, int] | None = None,
    destination: tuple[int, int, int] | None = None,
) -> DetailedRouteResult:
    failures: tuple[NetFailure, ...] = ()
    if status is not DetailedRouteStatus.ROUTED:
        net = NetId(0, 0, "item", NetRole.INTERNAL, 0)
        kind = failure_kind or (
            RouteFailureKind.CONGESTION_WALL
            if geometric_failure
            else RouteFailureKind.BUDGET
        )
        failures = (
            NetFailure(
                net_id=net,
                kind=kind,
                wall=(
                    ((0, 0, 0),)
                    if kind
                    not in {
                        RouteFailureKind.BUDGET,
                        RouteFailureKind.STATIC_ACCESS,
                    }
                    else ()
                ),
                blocking_nets=(),
                expansions=expansions,
                source=source,
                destination=destination,
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
    *,
    overflow: int = 0,
    expansions: int = 0,
    exhausted_budget: bool = False,
    cancelled: bool = False,
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
        exhausted_budget=exhausted_budget,
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
    prepared_candidates: list[Prepared] = field(default_factory=list)
    feedback_seen: list[FeedbackState] = field(default_factory=list)
    feedback_origins: Callable[[Prepared], tuple[tuple[int, int], ...]] | None = None
    _detailed_index: int = 0

    def prepare(self, height: int, decoded: DecodedPlacement) -> Prepared:
        self.stage_trace.append(height)
        self.prepared_candidates.append((height, decoded))
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
            return ValidationVerdict(ok=True, failed_checks=(), placement=placement)
        return ValidationVerdict(
            ok=False,
            failed_checks=("fake.invalid",),
            placement=None,
        )

    def adapters(self) -> StageAdapters[Prepared]:
        return StageAdapters(
            prepare=self.prepare,
            global_route=self.global_route,
            detailed_route=self.detailed_route,
            validate=self.validate,
            feedback_origins=self.feedback_origins,
        )


def _solver(
    fake: _FakeRouting,
    *,
    heights: tuple[int, ...] = (40, 60, 80),
    budget: ExpansionBudget | None = None,
    config: SequenceSolverConfig | None = None,
    deadline_reached: Callable[[], bool] | None = None,
    initial_states: dict[int, AnnealState] | None = None,
    borrow_first_discovery: bool = False,
    stage_admission: sequence_solver_module._MeasuredStageAdmission | None = None,
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
        initial_states=initial_states,
        borrow_first_discovery=borrow_first_discovery,
        stage_admission=stage_admission,
    )


def _repeat_merged_elite(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    original = build_elite_archive

    def repeat(
        candidates: Iterable[AnnealIncumbent],
        elite_count: int,
    ) -> tuple[TaggedAnnealIncumbent, ...]:
        archived = original(candidates, elite_count)
        if archived and elite_count == count:
            narrowest = next(
                tagged for tagged in archived if EliteCategory.NARROWEST in tagged.categories
            )
            return (narrowest,) * count
        return archived

    monkeypatch.setattr(sequence_solver_module, "build_elite_archive", repeat)


def test_absent_initial_state_keeps_exact_anneal_initial_and_mapping_is_validated() -> None:
    solver = _solver(_FakeRouting(), heights=(40,))
    for restart in solver._heights[0].restarts:
        assert restart.anneal == AnnealState.initial(1, restart.seed)

    with pytest.raises(ValueError, match="initial state height"):
        _solver(
            _FakeRouting(),
            heights=(40,),
            initial_states={60: AnnealState.initial(1, 1)},
        )


def test_validator_rejected_compact_seed_never_escapes_and_discovery_recovers() -> None:
    rejected = _placement(area=1, belt_tiles=1, valid=False)
    exact = _placement(area=20, belt_tiles=4)
    solver = _solver(
        _FakeRouting(
            detailed_results=(
                DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), rejected),
                DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),
            )
        ),
        heights=(40,),
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        initial_states={40: AnnealState.initial(1, 17)},
    )

    result = solver.search(max_stages=2)

    assert result.placement is exact
    seed_observation, discovery = result.stages
    assert seed_observation.global_skip_reason == "compact-seed"
    assert seed_observation.exact_key is None
    assert seed_observation.validation_failures == ("fake.invalid",)
    assert discovery.exact_key == (20, 4)


def test_compact_exact_incumbent_cannot_be_displaced_by_worse_discovery() -> None:
    compact_exact = _placement(area=20, belt_tiles=4)
    worse = _placement(area=30, belt_tiles=1)
    solver = _solver(
        _FakeRouting(
            detailed_results=(
                DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), compact_exact),
                DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), worse),
            )
        ),
        heights=(40,),
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        initial_states={40: AnnealState.initial(1, 17)},
    )

    result = solver.search(max_stages=2)

    assert result.placement is compact_exact
    assert result.exact_key == (20, 4)
    assert result.stages[0].global_skip_reason == "compact-seed"
    assert result.stages[1].exact_key == (30, 1)


def test_stable_exact_role_stops_before_a_third_non_improving_stage() -> None:
    compact_exact = _placement(area=20, belt_tiles=4)
    worse = _placement(area=30, belt_tiles=1)
    late_better = _placement(area=10, belt_tiles=8)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), compact_exact),
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), worse),
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), late_better),
        )
    )
    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig(
            stages=3,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        initial_states={40: AnnealState.initial(1, 17)},
    )
    solver.stop_on_stable_exact = True

    result = solver.search(max_stages=3)

    assert result.placement is compact_exact
    assert result.termination == "exact-stable"
    assert len(fake.detailed_allowances) == 2


def test_stable_exact_role_does_not_stop_after_stage_two_changed_the_incumbent() -> None:
    compact = _placement(area=30, belt_tiles=1)
    second_better = _placement(area=20, belt_tiles=4)
    temporarily_stable = _placement(area=25, belt_tiles=2)
    late_better = _placement(area=10, belt_tiles=8)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), compact),
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), second_better),
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), temporarily_stable),
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), late_better),
        )
    )
    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig(
            stages=4,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        initial_states={40: AnnealState.initial(1, 17)},
    )
    solver.stop_on_stable_exact = True

    result = solver.search(max_stages=4)

    assert result.placement is late_better
    assert result.termination == "stage-limit"
    assert len(fake.detailed_allowances) == 4


def test_exact_decoded_closure_retains_coordinates_without_sequence_reencoding() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(
                _routing(DetailedRouteStatus.ROUTED, expansions=7),
                exact,
            ),
        )
    )
    budget = ExpansionBudget(total=100)
    solver = _solver(fake, heights=(40,), budget=budget)
    decoded = DecodedPlacement(
        x=(7,),
        y=(11,),
        width=8,
        used_height=12,
        x_windows=((7, 7),),
        y_windows=((11, 11),),
        gap_area=0,
        variant_indices=(0,),
    )

    detailed = solver.close_exact_decoded(
        40,
        decoded,
        reason="topology-beam",
    )
    result = solver.search(max_stages=0)

    assert detailed.placement is exact
    assert fake.prepared_candidates == [(40, decoded)]
    assert result.placement is exact
    assert result.stages[0].global_skip_reason == "topology-beam"
    assert budget.spent == 7


def test_search_stops_when_exact_incumbent_meets_certified_area_floor() -> None:
    optimal = _placement(area=1, belt_tiles=1)
    unnecessary = _placement(area=2, belt_tiles=0)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(
                _routing(DetailedRouteStatus.ROUTED, expansions=3),
                optimal,
            ),
            DetailedStageResult(
                _routing(DetailedRouteStatus.ROUTED, expansions=5),
                unnecessary,
            ),
        )
    )
    solver = _solver(fake, heights=(40,))
    decoded = DecodedPlacement(
        x=(0,),
        y=(0,),
        width=1,
        used_height=1,
        x_windows=((0, 0),),
        y_windows=((0, 0),),
        gap_area=0,
        variant_indices=(0,),
    )

    solver.close_exact_decoded(40, decoded, reason="topology-beam")
    result = solver.search(max_stages=1)

    assert result.placement is optimal
    assert result.termination == "area-optimal"
    assert len(fake.detailed_allowances) == 1


def test_valid_topology_candidate_does_not_stop_better_exact_enumeration() -> None:
    first = _placement(area=30, belt_tiles=1)
    better = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(
                _routing(DetailedRouteStatus.ROUTED, expansions=7),
                first,
            ),
            DetailedStageResult(
                _routing(DetailedRouteStatus.ROUTED, expansions=11),
                better,
            ),
        )
    )
    budget = ExpansionBudget(total=100)
    solver = _solver(fake, heights=(40,), budget=budget)
    decoded = DecodedPlacement(
        x=(0,),
        y=(0,),
        width=1,
        used_height=1,
        x_windows=((0, 0),),
        y_windows=((0, 0),),
        gap_area=0,
        variant_indices=(0,),
    )

    solver.close_exact_decoded(40, decoded, reason="topology-beam")
    solver.close_exact_decoded(40, decoded, reason="topology-beam")
    result = solver.search(max_stages=0)

    assert result.placement is better
    assert [stage.exact_key for stage in result.stages] == [(30, 1), (20, 4)]
    assert budget.spent == 18
    assert fake.detailed_allowances == [100, 93]
    assert solver.exact_incumbent_reason == "topology-beam"


def test_exact_candidate_caps_preserve_later_closures_and_fallback_discovery() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fallback = _placement(area=25, belt_tiles=3)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(
                _routing(DetailedRouteStatus.BUDGET, expansions=10),
                None,
            ),
            DetailedStageResult(
                _routing(DetailedRouteStatus.ROUTED, expansions=5),
                exact,
            ),
            DetailedStageResult(
                _routing(DetailedRouteStatus.ROUTED, expansions=7),
                fallback,
            ),
        )
    )
    budget = ExpansionBudget(total=100)
    solver = _solver(fake, heights=(40,), budget=budget)
    decoded = DecodedPlacement(
        x=(0,),
        y=(0,),
        width=1,
        used_height=1,
        x_windows=((0, 0),),
        y_windows=((0, 0),),
        gap_area=0,
        variant_indices=(0,),
    )

    failed = solver.close_exact_decoded(
        40,
        decoded,
        reason="topology-beam",
        allowance_cap=10,
    )
    routed = solver.close_exact_decoded(
        40,
        decoded,
        reason="topology-beam",
        allowance_cap=10,
    )
    result = solver.search(max_stages=1)

    assert failed.routing.status is DetailedRouteStatus.BUDGET
    assert routed.placement is exact
    assert result.placement is exact
    assert fake.detailed_allowances[:2] == [10, 10]
    assert fake.detailed_allowances[2] > 0
    assert budget.spent == 22
    assert budget.spent < budget.total


def test_exact_seed_routing_failure_becomes_shared_search_feedback() -> None:
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(
                _routing(
                    DetailedRouteStatus.STRANDED,
                    geometric_failure=True,
                    failure_kind=RouteFailureKind.CONGESTION_WALL,
                    source=(3, 4, 0),
                    destination=(6, 7, 0),
                ),
                None,
            ),
        )
    )
    fake.feedback_origins = lambda _prepared: ((2, 3),)
    solver = _solver(fake, heights=(40,))
    decoded = DecodedPlacement(
        x=(0,),
        y=(0,),
        width=1,
        used_height=1,
        x_windows=((0, 0),),
        y_windows=((0, 0),),
        gap_area=0,
        variant_indices=(0,),
    )

    solver.close_exact_decoded(40, decoded, reason="topology-beam")

    feedback = solver._heights[0].feedback
    assert feedback.net_weight
    assert feedback.cell_history
    assert feedback.endpoint_offsets == {
        NetId(0, 0, "item", NetRole.INTERNAL, 0): ((1, 1, 0), (4, 4, 0))
    }


def test_compact_seed_near_miss_substitutes_local_repair_without_proxy() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(
                _routing(
                    DetailedRouteStatus.STRANDED,
                    geometric_failure=True,
                    failure_kind=RouteFailureKind.CONGESTION_WALL,
                ),
                None,
            ),
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),
        )
    )
    solver = _solver(
        fake,
        heights=(40, 60),
        initial_states={40: AnnealState.initial(1, 7)},
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )

    result = solver.search(max_stages=2)

    assert result.placement is exact
    assert [stage.height for stage in result.stages] == [40, 40]
    assert [stage.global_skip_reason for stage in result.stages] == [
        "compact-seed",
        "proxy-budget",
    ]
    assert fake.global_allowances == []
    assert fake.prepared_candidates[1][1].gap_area == 1


def test_geometric_near_miss_substitutes_feedback_candidate_before_next_height() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(
                _routing(
                    DetailedRouteStatus.STRANDED,
                    geometric_failure=True,
                    failure_kind=RouteFailureKind.CONGESTION_WALL,
                ),
                None,
            ),
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),
        )
    )
    solver = _solver(fake, heights=(40, 60))

    result = solver.search(max_stages=2)

    assert result.placement is exact
    assert [stage.height for stage in result.stages] == [40, 40]
    assert result.stages[0].lns_size == 1
    assert result.stages[1].global_skip_reason == "proxy-budget"
    assert len(fake.global_allowances) == 1


def test_unseeded_solver_has_no_compact_closure() -> None:
    exact = _placement(area=20, belt_tiles=4)
    solver = _solver(
        _FakeRouting(
            detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),)
        ),
        heights=(40,),
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )

    result = solver.search(max_stages=1)

    assert result.stages[0].global_skip_reason is None
    assert result.stages[0].anneal_stages == 1
    assert result.stages[0].anneal_moves == 1


def test_default_stage_limit_counts_grouped_discovery_as_one_routing_unit() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),)
    )
    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=2,
            global_elites=1,
        ),
    )

    result = solver.search()

    assert result.termination == "stage-limit"
    assert len(fake.detailed_allowances) == 3
    assert [restart.stages for restart in solver._heights[0].restarts] == [2, 2]


def test_zero_overflow_validator_clean_exact_enters_quality_mode() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),)
    )
    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )

    result = solver.search(max_stages=1)

    observation = result.stages[0]
    assert observation.objective_mode is sequence_solver_module.ObjectiveMode.QUALITY
    assert observation.quality_entered
    assert not observation.quality_exited
    assert observation.global_skip_reason is None
    assert solver._heights[0].objective_mode is sequence_solver_module.ObjectiveMode.QUALITY


@pytest.mark.parametrize(
    ("overflow", "first_valid"),
    ((1, True), (0, False)),
)
def test_quality_mode_requires_zero_overflow_and_validator_clean_exact(
    overflow: int,
    first_valid: bool,
) -> None:
    first = _placement(area=20, belt_tiles=4, valid=first_valid)
    second = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), first),
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), second),
        )
    )
    global_calls = 0

    def global_route(
        prepared: Prepared,
        feedback: FeedbackState,
        allowance: int,
    ) -> GlobalRouteResult:
        nonlocal global_calls
        del prepared, feedback, allowance
        global_calls += 1
        return _global(overflow=overflow)

    solver = SequenceSolver(
        heights=(40,),
        problem_for_height=lambda height: PlacementProblem(
            sizes=((1, 1),),
            nets=((0, 0),),
            outline_height=height,
            area_lower_bound=1,
        ),
        adapters=replace(fake.adapters(), global_route=global_route),
        expansion_budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )

    result = solver.search(max_stages=2)

    first_observation = result.stages[0]
    assert first_observation.objective_mode is sequence_solver_module.ObjectiveMode.EXPLORATION
    assert not first_observation.quality_entered
    assert first_observation.global_skip_reason is None
    assert global_calls == 2


def test_quality_geometric_failure_updates_feedback_and_repeated_signature() -> None:
    exact = _placement(area=20, belt_tiles=4)
    quality_failure = _routing(
        DetailedRouteStatus.STRANDED,
        failure_kind=RouteFailureKind.CONGESTION_WALL,
    )
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),
            DetailedStageResult(quality_failure, None),
            DetailedStageResult(quality_failure, None),
        )
    )
    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig(
            stages=3,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )

    first_result = solver.search(max_stages=2)

    failure = first_result.stages[1]
    restart = solver._heights[0].restarts[0]
    failed_net = quality_failure.failures[0].net_id
    expected_signature = (
        (
            failed_net.logical,
            RouteFailureKind.CONGESTION_WALL,
            (),
        ),
    )
    assert failure.global_routes == 0
    assert failure.global_skip_reason == "quality-mode"
    assert failure.objective_mode is sequence_solver_module.ObjectiveMode.EXPLORATION
    assert failure.quality_exited
    assert solver._heights[0].feedback.net_weight == {failed_net: 1.0}
    assert solver._heights[0].feedback.cell_history == {(0, 0, 0): 1.0}
    assert restart.failure_signature == expected_signature
    assert restart.feedback_stagnation == 1
    assert len(fake.global_allowances) == 1

    final_result = solver.search(max_stages=3)

    restored = final_result.stages[2]
    assert restored.global_routes == 1
    assert restored.global_skip_reason is None
    assert restored.objective_mode is sequence_solver_module.ObjectiveMode.EXPLORATION
    assert solver._heights[0].feedback.net_weight == {failed_net: 1.85}
    assert solver._heights[0].feedback.cell_history == {(0, 0, 0): 1.85}
    assert restart.failure_signature == expected_signature
    assert restart.feedback_stagnation == 2
    assert len(fake.global_allowances) == 2


@pytest.mark.parametrize(
    ("status", "kind"),
    (
        (DetailedRouteStatus.STRANDED, RouteFailureKind.STATIC_ACCESS),
        (DetailedRouteStatus.BUDGET, RouteFailureKind.BUDGET),
    ),
)
def test_quality_static_and_budget_failures_add_no_feedback_or_signature(
    status: DetailedRouteStatus,
    kind: RouteFailureKind,
) -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),
            DetailedStageResult(_routing(status, failure_kind=kind), None),
        )
    )
    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )

    result = solver.search(max_stages=2)

    restart = solver._heights[0].restarts[0]
    assert result.stages[1].quality_exited
    assert not solver._heights[0].feedback.net_weight
    assert not solver._heights[0].feedback.cell_history
    assert restart.failure_signature == ()
    assert restart.feedback_stagnation == 0


def test_best_height_scheduling_uses_complete_exact_key_before_stable_order() -> None:
    detailed_heights: list[int] = []

    def detailed_route(prepared: Prepared, allowance: int) -> DetailedStageResult:
        del allowance
        height, _decoded = prepared
        detailed_heights.append(height)
        return DetailedStageResult(
            _routing(DetailedRouteStatus.ROUTED),
            _placement(area=100, belt_tiles=10 if height == 40 else 1),
        )

    fake = _FakeRouting()
    solver = SequenceSolver(
        heights=(40, 60),
        problem_for_height=lambda height: PlacementProblem(
            sizes=((1, 1),),
            nets=((0, 0),),
            outline_height=height,
            area_lower_bound=1,
        ),
        adapters=replace(fake.adapters(), detailed_route=detailed_route),
        expansion_budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )

    result = solver.search(max_stages=3)

    assert [stage.height for stage in result.stages] == [40, 60, 60]
    assert detailed_heights == [40, 60, 60]
    assert result.exact_key == (100, 1)


def test_height_neighbor_gets_one_protected_followup_before_exact_key_best_first() -> None:
    detailed_calls: dict[int, int] = {26: 0, 31: 0}
    fake = _FakeRouting()

    def detailed_route(prepared: Prepared, allowance: int) -> DetailedStageResult:
        height, _decoded = prepared
        detailed_calls[height] += 1
        exact = {
            (31, 1): _placement(area=1888, belt_tiles=932),
            (31, 2): _placement(area=1888, belt_tiles=932),
            (26, 1): _placement(area=2139, belt_tiles=855),
            (26, 2): _placement(area=1728, belt_tiles=771),
        }[(height, detailed_calls[height])]
        return DetailedStageResult(
            _routing(DetailedRouteStatus.ROUTED, expansions=min(1, allowance)),
            exact,
        )

    budget = ExpansionBudget(100)
    solver = SequenceSolver(
        heights=(31, 26),
        problem_for_height=lambda height: PlacementProblem(
            sizes=((1, 1),),
            nets=((0, 0),),
            outline_height=height,
            area_lower_bound=1,
        ),
        adapters=replace(fake.adapters(), detailed_route=detailed_route),
        expansion_budget=budget,
        config=SequenceSolverConfig(
            stages=3,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        protected_followup_heights=(26,),
    )

    result = solver.search(max_stages=3)

    assert [stage.height for stage in result.stages] == [31, 26, 26]
    assert [stage.exact_key for stage in result.stages] == [
        (1888, 932),
        (2139, 855),
        (1728, 771),
    ]
    assert result.exact_key == (1728, 771)
    assert budget.spent == 3

    solver._heights[0].exact_key = (1, 0)
    continued = solver.search(max_stages=4)

    assert continued.stages[-1].height == 31
    assert detailed_calls == {26: 2, 31: 2}
    assert budget.spent == 4


def test_best_height_fallback_order_is_stranded_overflow_narrowest_spend_then_stable() -> None:
    solver = _solver(_FakeRouting(), heights=(40, 60))
    first, second = solver._heights
    placement_key = PlacementKey(
        x=(0,),
        y=(0,),
        dimensions=((1, 1),),
        east_gaps=(0,),
        north_gaps=(0,),
    )

    first.stranded, second.stranded = 0, 1
    first.global_overflow, second.global_overflow = 5, 0
    assert min(solver._heights, key=sequence_solver_module._height_priority) is first

    second.stranded = 0
    assert min(solver._heights, key=sequence_solver_module._height_priority) is second

    first.global_overflow = 0
    first.narrowest_key = (0, 10, 1, 0, 0.0, placement_key)
    second.narrowest_key = (0, 9, 1, 0, 0.0, placement_key)
    assert min(solver._heights, key=sequence_solver_module._height_priority) is second

    first.narrowest_key = second.narrowest_key
    first.spent, second.spent = 1, 0
    assert min(solver._heights, key=sequence_solver_module._height_priority) is second

    first.spent = 0
    assert min(solver._heights, key=sequence_solver_module._height_priority) is first


def test_detailed_route_retains_positive_work_when_global_spends_its_proxy_allowance() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),),
        spend_allowance=True,
    )

    result = _solver(
        fake,
        heights=(40,),
        budget=ExpansionBudget(total=100),
    ).search(max_stages=1)

    assert result.placement is exact
    assert fake.global_allowances == [56]
    assert fake.detailed_allowances == [19]


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


def test_selected_score_reaches_stage_and_exact_incumbent_observations() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),)
    )

    result = _solver(fake, heights=(40,)).search(max_stages=1)

    observation = result.stages[0]
    _height, decoded = fake.prepared_candidates[0]
    assert observation.breakdown is result.exact_breakdown
    assert observation.candidate_key == result.exact_candidate_key
    assert observation.energy == observation.breakdown.energy
    assert observation.breakdown.width == decoded.width
    assert observation.breakdown.used_height == decoded.used_height
    assert observation.breakdown.box_area == 1
    assert observation.breakdown.gap_area == decoded.gap_area
    assert observation.breakdown.weighted_hpwl == 0.0
    assert observation.breakdown.history_cost == 0.0
    assert observation.breakdown.missed_direct_inserts == 0
    assert observation.breakdown.hard_outline_overflow == max(
        0, decoded.used_height - observation.height
    )


def test_observation_mutation_or_removal_cannot_change_selected_state_or_key() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),)
    )
    result = _solver(fake, heights=(40,)).search(max_stages=1)
    observation = result.stages[0]
    mutated_breakdown = replace(
        observation.breakdown,
        width=observation.breakdown.width + 10_000,
        weighted_hpwl=observation.breakdown.weighted_hpwl + 10_000.0,
    )

    mutated = replace(
        result,
        exact_breakdown=mutated_breakdown,
        stages=(replace(observation, breakdown=mutated_breakdown),),
    )
    removed = replace(result, stages=())

    for observed in (mutated, removed):
        assert observed.placement is exact
        assert observed.exact_key == (20, 4)
        assert observed.exact_candidate_key == result.exact_candidate_key


def test_validator_rejection_never_establishes_an_exact_incumbent() -> None:
    invalid = _placement(area=10, belt_tiles=2, valid=False)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), invalid),)
    )
    with pytest.raises(NoValidLayout):
        _solver(fake, heights=(40,)).search(max_stages=1)


def test_refusal_accumulates_distinct_validation_failures() -> None:
    invalid = _placement(area=10, belt_tiles=2, valid=False)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), invalid),)
    )
    solver = _solver(fake, heights=(40, 60))
    failed_checks = iter(
        (
            ("validator.first", "validator.shared"),
            ("validator.second", "validator.shared"),
        )
    )
    solver.adapters = replace(
        solver.adapters,
        validate=lambda _placement: ValidationVerdict(
            ok=False,
            failed_checks=next(failed_checks),
            placement=None,
        ),
    )

    with pytest.raises(NoValidLayout) as caught:
        solver.search(max_stages=2)

    assert "no scheduled stage produced an exact layout" in caught.value.reason
    assert "validator.first" in caught.value.reason
    assert "validator.shared" in caught.value.reason
    assert "validator.second" in caught.value.reason
    assert caught.value.reason.count("validator.shared") == 1



def test_production_projection_refusals_reach_terminal_sequence_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    first = finalize.ProjectionFailure(
        check="geom.collide",
        buildings=(4, 9),
        detail="first projected collision",
        band=160,
    )
    shared = finalize.ProjectionFailure(
        check="game.power_too_close",
        buildings=(2, 7),
        detail="shared projected power refusal",
        band=200,
    )
    last = finalize.ProjectionFailure(
        check="geom.collide",
        buildings=(1, 8),
        detail="last projected collision",
        band=240,
    )
    batches = iter(((first, shared), (shared, last)))
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )

    def refuse_projection(
        _placement: Placement,
        _policy: BandPolicy,
    ) -> Never:
        raise finalize.ProjectionRefusal(next(batches))

    monkeypatch.setattr(finalize, "finalize_placement", refuse_projection)
    routed = _placement(area=10, belt_tiles=2)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), routed),)
    )
    solver = _solver(fake, heights=(40, 60))
    solver.adapters = replace(
        solver.adapters,
        validate=run.solver.adapters.validate,
    )

    with pytest.raises(NoValidLayout) as caught:
        solver.search(max_stages=2)

    assert "no scheduled stage produced an exact layout" in caught.value.reason
    assert (
        "exact validation failures: game.power_too_close, geom.collide"
        in caught.value.reason
    )
    for failure in (first, shared, last):
        record = (
            f"band {failure.band} {failure.check} "
            f"{failure.buildings}: {failure.detail}"
        )
        assert caught.value.reason.count(record) == 1
        assert record in str(caught.value)
    assert [
        (failure.band, failure.check, failure.buildings, failure.detail)
        for failure in caught.value.projection_failures
    ] == [
        (failure.band, failure.check, failure.buildings, failure.detail)
        for failure in (first, shared, last)
    ]

def test_stage_routes_preserve_the_final_twenty_five_percent() -> None:
    budget = ExpansionBudget(total=100)
    fake = _FakeRouting(spend_allowance=True)
    with pytest.raises(NoValidLayout):
        _solver(fake, heights=(40,), budget=budget).search(max_stages=20)
    assert budget.final_reserved == 25
    assert budget.spent == 75
    assert max(fake.global_allowances) == 56
    assert all(allowance > 0 for allowance in fake.detailed_allowances)
    assert sum(fake.global_allowances) + sum(fake.detailed_allowances) == 75


def test_compact_seed_closure_can_charge_the_detailed_final_reserve_once() -> None:
    budget = ExpansionBudget(total=100)
    fake = _FakeRouting(spend_allowance=True)
    solver = _solver(
        fake,
        heights=(40,),
        budget=budget,
        initial_states={40: AnnealState.initial(1, 7)},
    )

    with pytest.raises(NoValidLayout, match="no scheduled stage"):
        solver.search(max_stages=1)

    assert fake.global_allowances == []
    assert fake.detailed_allowances == [100]
    assert budget.spent == 100
    assert budget.final_reserved == 25
    assert budget.final_left == 0


def test_seed_closure_borrows_future_slices_in_stable_height_order() -> None:
    budget = ExpansionBudget(total=100)
    budget.configure((40, 60, 80), Fraction(1, 4))

    assert budget.detailed_discovery_allowance(40) == 100
    budget.charge_detailed_discovery(40, 90)

    assert budget.spent == 90
    assert budget.final_left == 0
    assert budget.discovery_allowance(40) == 0
    assert budget.discovery_allowance(60) == 0
    assert budget.discovery_allowance(80) == 10
    assert (
        budget.spent
        + budget.final_left
        + budget.shared_left
        + sum(budget.discovery_allowance(height) for height in budget.discovery_by_height)
        == budget.total
    )


def test_terminal_seed_fallback_borrows_only_for_detailed_closure() -> None:
    budget = ExpansionBudget(total=100)
    fake = _FakeRouting(spend_allowance=True)
    solver = _solver(
        fake,
        budget=budget,
        borrow_first_discovery=True,
    )

    with pytest.raises(NoValidLayout, match="no scheduled stage"):
        solver.search(max_stages=1)

    assert fake.global_allowances == []
    assert fake.detailed_allowances == [100]
    assert budget.spent == 100
    assert budget.final_left == 0


def test_casimir_sized_discovery_slices_conserve_900k_and_protect_detailed_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repeat_merged_elite(monkeypatch, 4)
    budget = ExpansionBudget(total=6_000_000)
    fake = _FakeRouting(spend_allowance=True)
    config = SequenceSolverConfig(
        stages=1,
        moves_per_stage=1,
        restarts_per_height=1,
        global_elites=4,
    )

    with pytest.raises(NoValidLayout, match="no scheduled stage"):
        _solver(
            fake,
            heights=tuple(range(10, 20)),
            budget=budget,
            config=config,
        ).search(max_stages=2)

    assert budget.discovery_by_height == dict.fromkeys(range(10, 20), 450_000)
    assert budget.spent == 900_000
    assert fake.global_allowances == [84_375] * 8
    assert fake.detailed_allowances == [112_500, 112_500]


def test_discovery_reservations_are_equal_and_unused_budget_is_shared_afterward() -> None:
    budget = ExpansionBudget(total=101)
    fake = _FakeRouting()
    with pytest.raises(NoValidLayout):
        _solver(fake, budget=budget).search(max_stages=4)
    assert budget.discovery_by_height == {40: 25, 60: 25, 80: 25}
    assert budget.final_reserved == 26
    assert fake.global_allowances[:3] == [18, 18, 18]
    assert fake.global_allowances[3] == 56


def test_measured_stage_admits_another_complete_stage_when_its_span_fits() -> None:
    now = 0.0
    detailed_calls = 0
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),)
    )

    def delayed_detailed_route(
        prepared: Prepared,
        allowance: int,
    ) -> DetailedStageResult:
        nonlocal now, detailed_calls
        detailed_calls += 1
        result = fake.detailed_route(prepared, allowance)
        now += 4.0
        return result

    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig(
            stages=3,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        stage_admission=sequence_solver_module._MeasuredStageAdmission(
            deadline=10.0,
            monotonic=lambda: now,
        ),
    )
    solver.adapters = replace(
        solver.adapters,
        detailed_route=delayed_detailed_route,
    )

    result = solver.search(max_stages=3)

    assert result.placement is exact
    assert result.termination == "deadline"
    assert detailed_calls == 2
    assert now == 8.0


def test_measured_stage_reserves_search_and_completion_spans_once_each() -> None:
    now = 0.0
    admission = sequence_solver_module._MeasuredStageAdmission(
        deadline=10.0,
        monotonic=lambda: now,
    )

    first = admission.try_start()
    assert first == 0.0
    now = 4.0
    admission.record_completion(1.0)
    admission.finish(first)

    assert admission.dearest_speculative_s == 3.0
    assert admission.dearest_completion_s == 1.0
    second = admission.try_start()
    assert second == 4.0
    now = 8.0
    admission.record_completion(1.0)
    admission.finish(second)

    assert admission.try_start() is None


def test_measured_stage_reserves_bounded_work_without_an_incumbent() -> None:
    now = 0.0
    admission = sequence_solver_module._MeasuredStageAdmission(
        deadline=10.0,
        monotonic=lambda: now,
    )
    first = admission.try_start()
    assert first == 0.0
    now = 4.0
    admission.record_completion(1.0)
    admission.finish(first)
    now = 8.0

    assert admission.try_start() is None

def test_later_cancelled_proxy_closes_the_best_completed_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repeat_merged_elite(monkeypatch, 3)
    exact = _placement(area=20, belt_tiles=4)
    global_allowances: list[int] = []
    detailed_allowances: list[int] = []

    def global_route(
        prepared: Prepared,
        feedback: FeedbackState,
        allowance: int,
    ) -> GlobalRouteResult:
        del prepared, feedback
        global_allowances.append(allowance)
        if len(global_allowances) == 1:
            return _global(
                overflow=1,
                expansions=allowance,
                exhausted_budget=True,
            )
        return _global(expansions=1, cancelled=True)

    def detailed_route(
        prepared: Prepared,
        allowance: int,
    ) -> DetailedStageResult:
        del prepared
        detailed_allowances.append(allowance)
        return DetailedStageResult(
            _routing(DetailedRouteStatus.ROUTED, expansions=allowance),
            exact,
        )

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
            validate=lambda placement: ValidationVerdict(True, (), placement),
        ),
        expansion_budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=3,
        ),
    )

    result = solver.search(max_stages=1)

    assert result.placement is exact
    assert global_allowances == [19, 19]
    assert detailed_allowances == [55]
    assert solver.budget.spent == 75


def test_unseatable_prepared_candidate_remains_searchable_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse_preparation(
        _spec: BuildSpec,
        _strips: list[freeform_module.Strip],
        _pack: freeform_module._Pack,
        *,
        policy: BandPolicy,
        power: bool,
        ramped: bool = False,
        _reserve_ports: bool = True,
    ) -> Never:
        del power, policy, ramped, _reserve_ports
        raise freeform_module._Unseatable("positional coater collision")

    monkeypatch.setattr(
        sequence_solver_module,
        "_prepare_routing_problem",
        refuse_preparation,
    )
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    height_state = run.solver._heights[0]
    candidate = run.solver.adapters.prepare(
        height_state.height,
        decode_state(
            height_state.problem,
            AnnealState.initial(height_state.problem.size, 7),
        ),
    )

    assert candidate.prepared is None
    assert candidate.preparation_error == "unseatable"


def test_production_detailed_adapter_withholds_budget_placement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, max(_box(strip)[1] for strip in strips))
    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False,
    )
    net_id = next(
        net.net_id
        for net in prepared.nets
        if net.net_id is not None and net.net_id.role is not NetRole.EXTERNAL
    )
    evidence = DetailedRouteResult(
        status=DetailedRouteStatus.BUDGET,
        routed=(),
        failures=(
            NetFailure(
                net_id,
                RouteFailureKind.BUDGET,
                (),
                (),
                9,
            ),
        ),
        iterations=1,
        expansions=9,
    )
    built = freeform_module._BuildResult(
        placement=None,
        routing=evidence,
        budget_stage=freeform_module._BuildBudgetStage.ROUTING,
        towers=(),
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_build_prepared",
        lambda *_args, **_kwargs: built,
    )

    result = sequence_solver_module._route_detailed_candidate(
        spec,
        strips,
        prepared,
        power=False,
        deadline=None,
        allowance=20,
    )

    assert result.routing is evidence
    assert result.placement is None


def test_cancelled_proxy_without_an_exact_candidate_remains_an_honest_refusal() -> None:
    detailed_allowances: list[int] = []

    def detailed_route(
        prepared: Prepared,
        allowance: int,
    ) -> DetailedStageResult:
        del prepared
        detailed_allowances.append(allowance)
        return DetailedStageResult(_routing(DetailedRouteStatus.UNPOWERABLE), None)

    solver = _solver(
        _FakeRouting(),
        heights=(40,),
        budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )
    solver.adapters = replace(
        solver.adapters,
        global_route=lambda _prepared, _feedback, _allowance: _global(cancelled=True),
        detailed_route=detailed_route,
    )

    with pytest.raises(NoValidLayout, match="no scheduled stage"):
        solver.search(max_stages=1)

    assert detailed_allowances == [75]


def test_parent_deadline_after_proxy_closure_is_not_proxy_cancellation() -> None:
    checks = iter((False, True))
    fake = _FakeRouting()
    solver = _solver(
        fake,
        heights=(40,),
        budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        deadline_reached=lambda: next(checks),
    )
    solver.adapters = replace(
        solver.adapters,
        global_route=lambda _prepared, _feedback, _allowance: _global(cancelled=True),
    )

    with pytest.raises(NoValidLayout, match="deadline exhausted"):
        solver.search(max_stages=1)

    assert fake.detailed_allowances == [75]


def _direct_pack_adapter_scene() -> tuple[
    BuildSpec,
    list[freeform_module.Strip],
    dict[tuple[int, int], freeform_module._DirectCandidate],
    freeform_module._Pack,
    PlacementProblem,
]:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    candidates = freeform_module._direct_net_candidates(strips, spec)
    height = sum(strip.height + 1 for strip in strips)
    pack = freeform_module._pack(
        strips,
        height=height,
        width_bound=max(strip.width + 1 for strip in strips) * 2,
        time_budget_s=0.5,
        direct_candidates=candidates,
        workers=1,
    )
    assert pack is not None and pack.direct
    sizes = tuple(_box(strip) for strip in strips)
    problem = PlacementProblem(
        sizes=sizes,
        nets=tuple(_nets_between(strips)),
        outline_height=height,
        area_lower_bound=sum(width * box_height for width, box_height in sizes),
    )
    return spec, strips, candidates, pack, problem


def test_exact_pack_decoded_projects_typed_direct_ids_to_sequence_pairs() -> None:
    _spec, strips, candidates, pack, problem = _direct_pack_adapter_scene()

    decoded = sequence_solver_module._exact_pack_decoded(
        pack,
        strips,
        problem,
        direct_candidates=candidates,
    )

    assert decoded.direct == frozenset(
        (direct.source_strip, direct.destination_strip) for direct in pack.direct
    )


def test_decoded_pack_reconstructs_typed_direct_ids_for_production_preparation() -> None:
    spec, strips, candidates, original, problem = _direct_pack_adapter_scene()
    x = tuple(
        original.at[index][0] - strips[index].west_channel
        for index in range(problem.size)
    )
    y = tuple(original.at[index][1] for index in range(problem.size))
    pairs = frozenset(
        (direct.source_strip, direct.destination_strip) for direct in original.direct
    )
    decoded = DecodedPlacement(
        x=x,
        y=y,
        width=original.width,
        used_height=max(
            coordinate + box_height
            for coordinate, (_width, box_height) in zip(
                y,
                problem.sizes,
                strict=True,
            )
        ),
        x_windows=tuple((coordinate, coordinate) for coordinate in x),
        y_windows=tuple((coordinate, coordinate) for coordinate in y),
        gap_area=0,
        direct=pairs,
        variant_indices=(0,) * problem.size,
    )

    rebuilt = _decoded_pack(
        problem.outline_height,
        decoded,
        west_channels=tuple(strip.west_channel for strip in strips),
        direct_candidates=candidates,
    )
    prepared = _prepare_routing_problem(
        spec,
        strips,
        rebuilt,
        power=False,
        policy=BandPolicy("portable"),
    )

    assert rebuilt.direct == original.direct
    assert prepared.promised_direct == original.direct


def test_decoded_pack_uses_each_selected_strip_west_channel() -> None:
    problem = PlacementProblem(
        sizes=((4, 3), (5, 2)),
        nets=(),
        outline_height=5,
        area_lower_bound=22,
    )
    decoded = decode_state(problem, AnnealState.initial(problem.size, 11))

    pack = _decoded_pack(
        problem.outline_height,
        decoded,
        west_channels=(3, 1),
    )

    assert pack.at == {
        0: (decoded.x[0] + 3, decoded.y[0]),
        1: (decoded.x[1] + 1, decoded.y[1]),
    }


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
        band_policy=BandPolicy("portable"),
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


def test_production_run_uses_requested_budget_with_supplied_absolute_deadline() -> None:
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
        absolute_deadline=time.monotonic() - 1.0,
    )

    assert run.solver.deadline_reached()
    assert run.ceiling == 2.0
    assert run.solver.budget.total == 2_000_000

def test_production_exact_preparation_propagates_deadline_and_reuses_only_pure_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caches: list[object] = []
    checks: list[bool] = []

    def cancelled_prepare(
        *_args: object,
        staged_static_cache: object,
        cancelled: Callable[[], bool],
        **_kwargs: object,
    ) -> Never:
        caches.append(staged_static_cache)
        checks.append(cancelled())
        raise freeform_module._PreparationDeadline

    monkeypatch.setattr(
        sequence_solver_module,
        "_prepare_routing_problem",
        cancelled_prepare,
    )
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    height = run.solver._heights[0]
    decoded = decode_state(height.problem, height.restarts[0].anneal)

    first = run.solver.adapters.prepare_exact(height.height, decoded)
    second = run.solver.adapters.prepare_exact(height.height, decoded)

    assert first.prepared is None
    assert first.preparation_error == "deadline"
    assert second.prepared is None
    assert second.preparation_error == "deadline"
    assert checks == [False, False]
    assert len(caches) == 2
    assert caches[0] is caches[1]

def test_production_exact_preparation_reuses_realized_direct_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    promised_direct: list[frozenset[freeform_module.DirectInsertId]] = []

    def capture_prepare(
        _spec: BuildSpec,
        _strips: list[freeform_module.Strip],
        pack: freeform_module._Pack,
        **_kwargs: object,
    ) -> Never:
        promised_direct.append(pack.direct)
        raise freeform_module._PreparationDeadline

    monkeypatch.setattr(
        sequence_solver_module,
        "_prepare_routing_problem",
        capture_prepare,
    )
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    height = run.solver._heights[0]
    decoded = decode_state(height.problem, height.restarts[0].anneal)

    candidate = run.solver.adapters.prepare_exact(height.height, decoded)

    assert candidate.decoded.x == decoded.x
    assert candidate.decoded.y == decoded.y
    assert promised_direct and promised_direct[0]


def test_sequence_pair_layout_rejects_removed_power_option() -> None:
    constructor: Callable[..., SequencePairLayout] = SequencePairLayout

    with pytest.raises(TypeError, match="unexpected keyword argument 'power'"):
        constructor(band_policy=BandPolicy("portable"), power=False)


def test_serial_layout_uses_a_budgeted_root_compact_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: _ProductionRunCapture = {}

    def stop_after_arguments(
        _spec: BuildSpec,
        *,
        time_budget_s: float,
        band_policy: BandPolicy,
        power: bool,
        strip_len: int,
        config: SequenceSolverConfig,
        belt_vertical_construction: bool = True,
        absolute_deadline: float | None = None,
        compact_seed_attempt: int | None = None,
        compact_seed_base_seed: int | None = None,
        compact_seed_config: CompactSeedConfig | None = None,
    ) -> Never:
        del (
            band_policy,
            time_budget_s,
            strip_len,
            config,
            belt_vertical_construction,
            absolute_deadline,
            compact_seed_base_seed,
        )
        captured["power"] = power
        captured["compact_seed_attempt"] = compact_seed_attempt
        captured["compact_seed_config"] = compact_seed_config
        raise RuntimeError("captured production arguments")

    monkeypatch.setattr(
        sequence_solver_module,
        "_production_run",
        stop_after_arguments,
    )

    with pytest.raises(RuntimeError, match="captured production arguments"):
        SequencePairLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(two_stage_spec(), time_budget_s=2.0)

    assert captured["compact_seed_attempt"] == 0
    compact_config = captured["compact_seed_config"]
    assert isinstance(compact_config, CompactSeedConfig)
    assert compact_config.max_deterministic_time == pytest.approx(2.0 / 15.0)
    assert captured["power"] is True


def test_serial_attempt_policy_selects_only_measured_topology_roles() -> None:
    assert sequence_solver_module._serial_compact_seed_attempt(95, 27, power=False) == 4
    assert sequence_solver_module._serial_compact_seed_attempt(95, 27, power=True) == 4
    assert sequence_solver_module._serial_compact_seed_attempt(146, 47, power=False) == 1
    assert sequence_solver_module._serial_compact_seed_attempt(146, 47, power=True) == 4
    assert sequence_solver_module._serial_compact_seed_attempt(331, 0, power=False) == 0
    assert sequence_solver_module._serial_compact_seed_attempt(331, 0, power=True) == 0
    assert sequence_solver_module._serial_compact_seed_attempt(278, 6, power=False) == 1
    assert sequence_solver_module._serial_compact_seed_attempt(278, 6, power=True) == 0
    assert sequence_solver_module._serial_compact_seed_attempt(168, 2, power=False) == 0
    assert sequence_solver_module._serial_compact_seed_attempt(58, 23, power=False) == 0

@pytest.mark.parametrize(
    ("requested", "sprayed_lanes", "direct_candidates", "expected"),
    (
        (4, 27, 0, 16),
        (16, 27, 0, 16),
        (4, 9, 0, 4),
        (4, 47, 7, 4),
        (4, 2, 0, 4),
    ),
)
def test_dense_spray_without_direct_structure_uses_coarse_initial_strips(
    requested: int,
    sprayed_lanes: int,
    direct_candidates: int,
    expected: int,
) -> None:
    assert (
        sequence_solver_module._dense_spray_initial_strip_len(
            requested,
            sprayed_lanes=sprayed_lanes,
            direct_candidates=direct_candidates,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("requested", "strip_count", "direct_candidates", "expected"),
    (
        (4, 24, 24, 12),
        (6, 37, 62, 12),
        (4, 64, 64, 12),
        (4, 23, 23, 4),
        (4, 65, 102, 4),
        (4, 53, 5, 4),
        (16, 50, 50, 16),
    ),
)
def test_moderate_routed_plan_preserves_partition_granularity(
    requested: int,
    strip_count: int,
    direct_candidates: int,
    expected: int,
) -> None:
    assert (
        sequence_solver_module._moderate_routed_initial_strip_len(
            requested,
            strip_count=strip_count,
            direct_candidates=direct_candidates,
        )
        == expected
    )


def test_topology_budget_signature_only_tracks_incomplete_failure_cardinality() -> None:
    budget = DetailedStageResult(_routing(DetailedRouteStatus.BUDGET), None)
    stranded = DetailedStageResult(_routing(DetailedRouteStatus.STRANDED), None)

    assert sequence_solver_module._topology_budget_signature(budget) == 1
    assert sequence_solver_module._topology_budget_signature(stranded) is None


def test_broad_topology_budget_requires_half_the_beam_strips_unresolved() -> None:
    assert not sequence_solver_module._topology_budget_is_broad(
        4,
        strip_count=10,
    )
    assert sequence_solver_module._topology_budget_is_broad(
        5,
        strip_count=10,
    )
    assert not sequence_solver_module._topology_budget_is_broad(
        0,
        strip_count=1,
    )


def test_small_direct_shared_pack_uses_the_wider_height_rank() -> None:
    assert (
        sequence_solver_module._shared_pack_height_rank(
            machine_count=21,
            strip_count=7,
            strip_len=6,
            sprayed_lanes=0,
            direct_candidates=7,
        )
        == 3
    )
    assert (
        sequence_solver_module._shared_pack_height_rank(
            machine_count=18,
            strip_count=4,
            strip_len=6,
            sprayed_lanes=0,
            direct_candidates=3,
        )
        != 3
    )
    assert (
        sequence_solver_module._shared_pack_height_rank(
            machine_count=9,
            strip_count=6,
            strip_len=6,
            sprayed_lanes=0,
            direct_candidates=6,
        )
        != 3
    )


def test_dense_topology_seed_role_uses_average_strip_occupancy() -> None:
    assert sequence_solver_module._topology_seed_is_terminal(
        machine_count=35,
        strip_count=10,
        strip_len=6,
    )
    assert not sequence_solver_module._topology_seed_is_terminal(
        machine_count=20,
        strip_count=7,
        strip_len=6,
    )
    assert not sequence_solver_module._topology_seed_is_terminal(
        machine_count=21,
        strip_count=7,
        strip_len=6,
    )


@pytest.mark.parametrize(
    (
        "exact_seed_terminal",
        "strip_count",
        "net_count",
        "sprayed_lanes",
        "expected",
    ),
    (
        (True, 10, 20, 0, 0),
        (False, 1, 0, 0, 1),
        (False, 6, 5, 2, 2),
        (False, 7, 5, 2, None),
        (False, 6, 5, 1, None),
    ),
)
def test_search_stage_cap_follows_certified_and_small_complexity_roles(
    exact_seed_terminal: bool,
    strip_count: int,
    net_count: int,
    sprayed_lanes: int,
    expected: int | None,
) -> None:
    assert (
        sequence_solver_module._search_stage_cap(
            exact_seed_terminal=exact_seed_terminal,
            strip_count=strip_count,
            net_count=net_count,
            sprayed_lanes=sprayed_lanes,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("machine_count", "strip_count", "sprayed_lanes", "expected"),
    (
        (8, 4, 0, True),
        (7, 4, 0, False),
        (8, 4, 1, False),
    ),
)
def test_stable_exact_role_is_unsprayed_with_two_machines_per_strip(
    machine_count: int,
    strip_count: int,
    sprayed_lanes: int,
    expected: bool,
) -> None:
    assert (
        sequence_solver_module._uses_stable_exact_stop(
            machine_count=machine_count,
            strip_count=strip_count,
            sprayed_lanes=sprayed_lanes,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("direct_candidates", "strip_count", "strip_len", "expected"),
    (
        (4, 7, 6, True),
        (3, 7, 6, False),
        (4, 8, 6, False),
    ),
)
def test_small_direct_seed_role_requires_dense_direct_opportunity(
    direct_candidates: int,
    strip_count: int,
    strip_len: int,
    expected: bool,
) -> None:
    assert (
        sequence_solver_module._small_direct_seed_role(
            direct_candidates=direct_candidates,
            strip_count=strip_count,
            strip_len=strip_len,
        )
        is expected
    )


@pytest.mark.parametrize(
    (
        "machine_count",
        "strip_count",
        "strip_len",
        "sprayed_lanes",
        "direct_candidates",
        "expected",
    ),
    (
        (20, 7, 6, 0, 4, 0),
        (95, 27, 6, 27, 0, 2),
        (16, 4, 6, 2, 0, 2),
        (9, 3, 6, 2, 0, 0),
    ),
)
def test_shared_pack_height_rank_follows_structural_role(
    machine_count: int,
    strip_count: int,
    strip_len: int,
    sprayed_lanes: int,
    direct_candidates: int,
    expected: int,
) -> None:
    assert (
        sequence_solver_module._shared_pack_height_rank(
            machine_count=machine_count,
            strip_count=strip_count,
            strip_len=strip_len,
            sprayed_lanes=sprayed_lanes,
            direct_candidates=direct_candidates,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("machine_count", "strip_count", "sprayed_lanes", "expected"),
    (
        (57, 14, 14, True),
        (75, 17, 3, True),
        (95, 27, 27, False),
        (57, 14, 0, False),
    ),
)
def test_tall_topology_role_is_sprayed_and_saturated(
    machine_count: int,
    strip_count: int,
    sprayed_lanes: int,
    expected: bool,
) -> None:
    assert (
        sequence_solver_module._uses_tall_topology_height(
            machine_count=machine_count,
            strip_count=strip_count,
            sprayed_lanes=sprayed_lanes,
        )
        is expected
    )


def test_tall_topology_height_uses_narrowest_greedy_bound_rank() -> None:
    assert (
        sequence_solver_module._topology_beam_height(
            {},
            (89, 70, 56, 44, 33),
            machine_count=57,
            strip_count=14,
            sprayed_lanes=14,
            power=False,
        )
        == 89
    )



@pytest.mark.parametrize(
    ("machine_count", "strip_count", "sprayed_lanes", "expected"),
    (
        (58, 18, 23, True),
        (57, 14, 14, False),
        (95, 27, 27, False),
        (58, 18, 3, False),
    ),
)
def test_mid_height_topology_role_is_high_spray_and_under_saturated(
    machine_count: int,
    strip_count: int,
    sprayed_lanes: int,
    expected: bool,
) -> None:
    assert (
        sequence_solver_module._uses_mid_topology_height(
            machine_count=machine_count,
            strip_count=strip_count,
            sprayed_lanes=sprayed_lanes,
        )
        is expected
    )


def test_tall_topology_role_protects_every_measured_candidate() -> None:
    assert (
        sequence_solver_module._protected_topology_candidates(
            strip_count=14,
            sprayed_lanes=14,
            tall_role=True,
        )
        == 7
    )
    assert (
        sequence_solver_module._protected_topology_candidates(
            strip_count=14,
            sprayed_lanes=14,
            tall_role=False,
        )
        == 3
    )

@pytest.mark.parametrize(
    ("tall_role",),
    ((False,), (True,)),
    ids=("ordinary", "tall-direct-refinement"),
)
def test_topology_candidate_zero_survives_single_admission_and_tall_refinement(
    monkeypatch: pytest.MonkeyPatch,
    tall_role: bool,
) -> None:
    closed: list[tuple[int, ...]] = []

    class FirstOnlyAdmission:
        def __init__(self, **_kwargs: object) -> None:
            self.starts = 0

        def try_start(self) -> float | None:
            self.starts += 1
            return 0.0 if self.starts == 1 else None

        def finish(self, _started: float) -> None:
            return None

    class CandidateZeroBeam:
        def __init__(
            self,
            problem: PlacementProblem,
            *,
            coordinate_hint: DecodedPlacement,
            config: object,
            **_kwargs: object,
        ) -> None:
            self.problem = problem
            self.hint = coordinate_hint
            self.config = config

        def solve_next(self, **_kwargs: object) -> CompactTopologyCandidate:
            pairs = tuple(
                ((first, second), (True, False, False, False))
                for first in range(self.problem.size)
                for second in range(first + 1, self.problem.size)
            )
            return CompactTopologyCandidate(
                topology_index=0,
                status=CompactSeedStatus.FEASIBLE,
                x=self.hint.x,
                y=self.hint.y,
                width=self.hint.width,
                used_height=self.hint.used_height,
                variant_indices=self.hint.variant_indices,
                signature=PairwiseRelationSignature(pairs),
                deterministic_time=0.0,
            )

        def exclude(self, _signature: PairwiseRelationSignature) -> None:
            return None

    def close_candidate_zero(
        _solver: SequenceSolver[object],
        _height: int,
        decoded: DecodedPlacement,
        *,
        reason: str,
        allowance_cap: int | None = None,
    ) -> DetailedStageResult:
        del allowance_cap
        if tall_role:
            class Stage:
                exact_key: tuple[int, int] | None = None

            _solver._stage_stats.append(Stage())  # type: ignore[arg-type]
        assert reason == "topology-beam"
        closed.append(decoded.x)
        return sequence_solver_module._closed_detailed_result(
            DetailedRouteStatus.STRANDED
        )

    monkeypatch.setattr(
        sequence_solver_module,
        "_MeasuredStageAdmission",
        FirstOnlyAdmission,
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_topology_beam_height",
        lambda _seeds, coarse, **_kwargs: coarse[0],
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_uses_topology_beam",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_uses_tall_topology_height",
        lambda **_kwargs: tall_role,
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_direct_alignment_targets",
        lambda _candidates: (
            DirectInsertTarget((0, 1), 0, 1, 0, 0, 1, 1, (0,)),
        ),
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_uses_sparse_compact_topology_diversity",
        lambda **_kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "CompactTopologyBeam",
        CandidateZeroBeam,
    )
    monkeypatch.setattr(
        sequence_solver_module.SequenceSolver,
        "close_exact_decoded",
        close_candidate_zero,
    )

    _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )

    assert len(closed) == 1


@pytest.mark.parametrize(
    ("allowance", "quality_role", "expected"),
    (
        (333_333, True, 50_000),
        (40_000, True, 40_000),
        (333_333, False, 333_333),
    ),
)
def test_quality_topology_roles_cap_speculative_closures(
    allowance: int,
    quality_role: bool,
    expected: int,
) -> None:
    assert (
        sequence_solver_module._topology_closure_allowance(
            allowance,
            quality_role=quality_role,
        )
        == expected
    )


def test_refinement_hint_retains_exact_better_belt_tie() -> None:
    first = DecodedPlacement(
        (0,),
        (0,),
        1,
        1,
        ((0, 0),),
        ((0, 0),),
        0,
    )
    narrower = replace(first, x=(1,), x_windows=((1, 1),), width=2)
    exact_better = replace(first, y=(1,), y_windows=((1, 1),), used_height=2)

    retained = sequence_solver_module._retain_refinement_hint(
        None,
        width=125,
        exact_key=(20, 4),
        decoded=first,
    )
    assert retained == (125, (20, 4), first)
    retained = sequence_solver_module._retain_refinement_hint(
        retained,
        width=111,
        exact_key=(21, 0),
        decoded=narrower,
    )
    assert retained == (111, (21, 0), narrower)
    retained = sequence_solver_module._retain_refinement_hint(
        retained,
        width=111,
        exact_key=(20, 3),
        decoded=exact_better,
    )
    assert retained == (111, (20, 3), exact_better)
    assert (
        sequence_solver_module._retain_refinement_hint(
            retained,
            width=112,
            exact_key=(10, 0),
            decoded=first,
        )
        == retained
    )


def test_tall_topology_closes_only_running_narrowest_widths() -> None:
    assert sequence_solver_module._is_running_narrowest(125, None)
    assert sequence_solver_module._is_running_narrowest(111, 125)
    assert sequence_solver_module._is_running_narrowest(111, 111)
    assert not sequence_solver_module._is_running_narrowest(125, 111)


def test_refinement_direct_targets_encode_strip_channel_offsets() -> None:
    target = DirectInsertTarget(
        (0, 1),
        0,
        1,
        2,
        4,
        10,
        4,
        tuple(range(-3, 10)),
    )
    strips = (
        type("StripOffset", (), {"west_channel": 3})(),
        type("StripOffset", (), {"west_channel": 1})(),
    )

    assert sequence_solver_module._refinement_direct_targets((target,), strips) == (
        replace(
            target,
            producer_span=12,
            consumer_span=2,
            origin_deltas=tuple(range(-1, 12)),
        ),
    )


def test_speculative_closure_allowance_reserves_half_for_fallback() -> None:
    speculative_candidates = 1 + 8 + 1
    allowance = sequence_solver_module._speculative_exact_allowance(
        6_000_000,
        speculative_candidates=speculative_candidates,
    )

    assert allowance == 300_000
    assert allowance * speculative_candidates <= 6_000_000 // 2


@pytest.mark.parametrize(
    ("topology_role", "shared_role", "incumbent_reason", "expected"),
    (
        (True, False, None, True),
        (False, True, None, True),
        (False, True, "shared-pack", False),
        (False, False, None, False),
    ),
)
def test_topology_beam_runs_for_its_role_or_a_failed_shared_seed(
    topology_role: bool,
    shared_role: bool,
    incumbent_reason: str | None,
    expected: bool,
) -> None:
    assert (
        sequence_solver_module._needs_topology_beam(
            topology_role=topology_role,
            shared_role=shared_role,
            incumbent_reason=incumbent_reason,
        )
        is expected
    )


def test_production_seed_has_its_own_wall_and_deterministic_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: _CompactSeedCapture = {}

    def capture_seed(
        _problem: PlacementProblem,
        *,
        base_seed: int,
        attempt: int,
        config: CompactSeedConfig | None = None,
        direct_eligibility: tuple[VariantDirectInsertTarget, ...] = (),
        absolute_deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> CompactSeedResult:
        del base_seed, attempt, cancelled
        captured["called_at"] = time.monotonic()
        captured["config"] = config
        captured["direct_eligibility"] = direct_eligibility
        captured["absolute_deadline"] = absolute_deadline
        return CompactSeedResult(
            CompactSeedStatus.CANCELLED,
            None,
            CompactSeedDiagnostics(
                solver_seed=0,
                status_name="CANCELLED",
                width_weight=1,
                secondary_upper_bound=0,
            ),
        )

    monkeypatch.setattr(sequence_solver_module, "solve_compact_seed", capture_seed)
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
        compact_seed_attempt=0,
    )
    assert run.heights[0] == run.telemetry.compact_seed_height

    compact_config = captured["config"]
    assert isinstance(compact_config, CompactSeedConfig)
    assert compact_config.max_deterministic_time == pytest.approx(2.0 / 15.0)
    compact_deadline = captured["absolute_deadline"]
    called_at = captured["called_at"]
    assert captured["direct_eligibility"] == ()
    assert isinstance(compact_deadline, float)
    assert 0.0 < compact_deadline - called_at <= 2.0 / 3.0


def test_validator_crossing_deadline_returns_incomplete_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Report:
        errors: tuple[()] = ()

    now = [0.0]
    certify_called = [False]

    def crossing_certify(
        _placement: Placement,
        _spec: BuildSpec,
        *,
        expect_power: bool,
    ) -> Report:
        del expect_power
        certify_called[0] = True
        now[0] = 2.0
        return Report()

    monkeypatch.setattr(sequence_solver_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(validate, "certify", crossing_certify)
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
        absolute_deadline=1.0,
    )

    candidate = _placement(area=1, belt_tiles=1)
    verdict = run.solver.adapters.validate(candidate)
    assert certify_called == [True]

    assert not verdict.ok
    assert verdict.status is DetailedRouteStatus.BUDGET
    assert verdict.failed_checks == ()
    assert verdict.placement is None


def test_deadline_without_an_exact_incumbent_raises() -> None:
    with pytest.raises(NoValidLayout, match="deadline exhausted"):
        _solver(_FakeRouting(), deadline_reached=lambda: True).search(max_stages=5)


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
    policy = BandPolicy("portable")
    default = (0,) * problem.size
    baseline = _selected_direct_targets(
        spec,
        strips,
        problem,
        default,
        band_policy=policy,
    )
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
        and _selected_direct_targets(
            spec,
            strips,
            problem,
            selection,
            band_policy=policy,
        )[0].producer_row
        != target.producer_row
    )
    consumer_selection = tuple(
        4 if strip == target.consumer else 0 for strip in range(problem.size)
    )

    producer_changed = _selected_direct_targets(
        spec,
        strips,
        problem,
        producer_selection,
        band_policy=policy,
    )[0]
    consumer_plans = _selected_strips(
        strips,
        problem,
        consumer_selection,
        band_policy=policy,
    )
    consumer_changed = _selected_direct_targets(
        spec,
        strips,
        problem,
        consumer_selection,
        band_policy=policy,
    )[0]
    assert producer_changed.producer_row != target.producer_row
    assert producer_changed.consumer_row == target.consumer_row
    assert (
        consumer_plans[target.consumer].lane_plan
        != _selected_strips(
            strips,
            problem,
            default,
            band_policy=policy,
        )[target.consumer].lane_plan
    )
    assert (
        consumer_changed
        == freeform_module._direct_alignment_targets(
            freeform_module._direct_net_candidates(consumer_plans, spec)
        )[0]
    )
    assert consumer_changed.producer_row == target.producer_row


def test_compact_direct_eligibility_contains_exactly_authoritative_variant_targets() -> None:
    spec, strips, problem = _two_stage_variant_problem()
    policy = BandPolicy("portable")
    enumerate_eligibility = getattr(
        sequence_solver_module,
        "_variant_direct_eligibility",
        None,
    )
    assert enumerate_eligibility is not None

    actual = enumerate_eligibility(
        spec,
        strips,
        problem,
        band_policy=policy,
    )
    expected: set[VariantDirectInsertTarget] = set()
    for baseline in _selected_direct_targets(
        spec,
        strips,
        problem,
        (0,) * problem.size,
        band_policy=policy,
    ):
        for producer_variant in range(len(problem.variant_tables[baseline.producer])):
            for consumer_variant in range(len(problem.variant_tables[baseline.consumer])):
                selection = [0] * problem.size
                selection[baseline.producer] = producer_variant
                selection[baseline.consumer] = consumer_variant
                selected = {
                    target.key: target
                    for target in _selected_direct_targets(
                        spec,
                        strips,
                        problem,
                        tuple(selection),
                        band_policy=policy,
                    )
                }
                target = selected.get(baseline.key)
                if target is not None:
                    expected.add(
                        VariantDirectInsertTarget(
                            producer_variant,
                            consumer_variant,
                            target,
                        )
                    )

    assert actual
    assert set(actual) == expected
    assert len(actual) == len(expected)


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
    selected = _selected_strips(
        strips,
        split.problem,
        split.state.variant_indices,
        band_policy=BandPolicy("portable"),
    )

    assert [strip.machines for strip in selected[target : target + 2]] == [
        split.problem.instance_ids[target].machine_count,
        split.problem.instance_ids[target + 1].machine_count,
    ]
    assert [strip.machine_start for strip in selected[target : target + 2]] == [
        split.problem.instance_ids[target].machine_start,
        split.problem.instance_ids[target + 1].machine_start,
    ]
    assert all(strip.family_id is not None for strip in selected)

@pytest.mark.parametrize(
    ("risky_yaw", "expected_west_channels"),
    (
        pytest.param(
            0.0,
            (
                freeform_module._COATER_WEST_CHANNEL + 1,
                freeform_module._COATER_WEST_CHANNEL,
            ),
            id="W4-to-W3",
        ),
        pytest.param(
            90.0,
            (
                freeform_module._COATER_WEST_CHANNEL,
                freeform_module._COATER_WEST_CHANNEL + 1,
            ),
            id="W3-to-W4",
        ),
    ),
)
def test_selected_variant_recomputes_its_own_staged_static_clearance(
    monkeypatch: pytest.MonkeyPatch,
    risky_yaw: float,
    expected_west_channels: tuple[int, int],
) -> None:
    spec = proliferated_spec()
    policy = BandPolicy("120")
    strips = sequence_solver_module._sequence_reservation_strips(
        plan_strips(spec, strip_len=6, band_policy=policy)
    )
    instance_ids, variant_tables = _variant_search_inputs(
        spec,
        strips,
        strip_len=6,
    )
    target = next(
        index
        for index, strip in enumerate(strips)
        if strip.cargo_domain is freeform_module.CargoDomain.REQUIRES_SPRAY
        and {variant.yaw for variant in variant_tables[index]} >= {0.0, 90.0}
    )
    problem = PlacementProblem(
        sizes=tuple(_box(strip) for strip in strips),
        nets=tuple(_nets_between(strips)),
        outline_height=40,
        area_lower_bound=1,
        instance_ids=instance_ids,
        variant_tables=variant_tables,
    )
    proof_policies: list[BandPolicy] = []

    def prove_relation(
        relation: freeform_module.StagedStaticClearanceKey,
        selected_policy: BandPolicy,
    ) -> bool:
        proof_policies.append(selected_policy)
        return relation.peer_yaw == risky_yaw

    monkeypatch.setattr(
        sequence_solver_module,
        "_staged_static_preclearance_proved",
        prove_relation,
    )
    selections = tuple(
        tuple(
            next(
                variant_index
                for variant_index, variant in enumerate(variant_tables[target])
                if variant.yaw == yaw
            )
            if strip == target
            else 0
            for strip in range(problem.size)
        )
        for yaw in (0.0, 90.0)
    )
    selected = tuple(
        _selected_strips(
            strips,
            problem,
            selection,
            band_policy=policy,
        )[target]
        for selection in selections
    )

    assert tuple(strip.west_channel for strip in selected) == expected_west_channels
    assert tuple(strip.physical_variant for strip in selected) == tuple(
        problem.variant(target, selection[target]) for selection in selections
    )
    assert all(
        problem.selected_sizes(selection)[target][0] >= _box(strip)[0]
        for selection, strip in zip(selections, selected, strict=True)
    )
    assert proof_policies
    assert set(proof_policies) == {policy}


def test_prepared_physical_nets_keep_stable_logical_family_edges() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    height = sum(_box(strip)[1] for strip in strips)
    prepared = _prepare_routing_problem(
        spec,
        strips,
        _greedy_pack(strips, height),
        policy=BandPolicy("portable"),
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
        band_policy=BandPolicy("portable"),
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
        DetailedStageResult(result, None),
        2,
        (),
        True,
    )
    alternate = transform(
        height_state.height,
        problem,
        alternate_state,
        height_state.feedback,
        DetailedStageResult(result, None),
        2,
        (),
        False,
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
            band_policy=BandPolicy("portable"),
        )
        assert update.problem.selected_sizes(update.state.variant_indices) == tuple(
            _box(strip) for strip in selected
        )

    commit = run.solver.stage_boundary_commit
    assert commit is not None
    commit(height_state.height, alternate.problem)

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


def _projection_pitch_stage_fixture() -> tuple[
    PlacementProblem,
    AnnealState,
    Placement,
    finalize.ProjectionFailure,
]:
    (family,) = generate_strip_families(projected_chemical_plant_spec())
    (instance,) = partition_strip_family(family, max_machine_count=2)
    variants = variants_for_count(family, 2)
    ordinary = variants[0]
    problem = PlacementProblem(
        sizes=((ordinary.box_width, ordinary.box_height),),
        nets=(),
        outline_height=40,
        area_lower_bound=1,
        instance_ids=(instance.instance_id,),
        variant_tables=(variants,),
    )
    state = AnnealState(
        pair=SequencePair((0,), (0,)),
        gaps=GapProfile.zero(1),
        base_seed=17,
        variant_indices=(0,),
    )
    placement = Placement(
        buildings=tuple(
            PlacedBuilding(
                item_id=2309,
                model_index=64,
                x=3 + origin,
                y=11 + ordinary.lane_plan.machine_row,
                width=ordinary.footprint_width,
                height=ordinary.footprint_height,
                yaw=ordinary.yaw,
                owner_strip=0,
            )
            for origin in ordinary.machine_origins_x
        )
    )
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (0, 1),
        "build colliders intersect",
        160,
    )
    return problem, state, placement, failure

def test_stage_projection_pitch_requirement_batches_ordered_failures_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem, state, placement, failure = _projection_pitch_stage_fixture()
    unrelated = replace(failure, check="game.power_too_close")
    reversed_pair = replace(failure, buildings=tuple(reversed(failure.buildings)))
    failures = (unrelated, failure, reversed_pair)
    calls: list[tuple[finalize.ProjectionFailure, ...]] = []
    mapper = sequence_solver_module.projection_pitch_requirements

    def record_batch(
        placement: Placement,
        *,
        instance_ids: tuple[StripInstanceId, ...],
        variants: tuple[StripVariant, ...],
        failures: tuple[finalize.ProjectionFailure, ...],
    ) -> tuple[ProjectionPitchRequirement | None, ...]:
        calls.append(failures)
        return mapper(
            placement,
            instance_ids=instance_ids,
            variants=variants,
            failures=failures,
        )

    monkeypatch.setattr(
        sequence_solver_module,
        "projection_pitch_requirements",
        record_batch,
    )

    requirement = sequence_solver_module._stage_projection_pitch_requirement(
        problem,
        state,
        placement,
        failures,
    )

    assert calls == [failures]
    assert requirement is not None
    assert requirement.failure is failure


def test_projection_pitch_feedback_rebuilds_failed_restart_and_rebases_siblings() -> None:
    problem, state, placement, failure = _projection_pitch_stage_fixture()
    config = SequenceSolverConfig(
        stages=1,
        moves_per_stage=1,
        restarts_per_height=2,
        global_elites=1,
    )
    budget = ExpansionBudget(17)
    transform_calls: list[
        tuple[
            tuple[finalize.ProjectionFailure, ...],
            bool,
            tuple[int, ...],
            int,
        ]
    ] = []
    transform_updates: list[tuple[bool, StageBoundaryUpdate]] = []
    feedback_variant: tuple[int, StripVariant] | None = None

    def transform(
        _height: int,
        stage_problem: PlacementProblem,
        stage_state: AnnealState,
        _feedback: FeedbackState,
        detailed: DetailedStageResult,
        stagnation: int,
        projection_failures: tuple[finalize.ProjectionFailure, ...],
        select_feedback_variant: bool,
    ) -> StageBoundaryUpdate | None:
        nonlocal feedback_variant
        transform_calls.append(
            (
                projection_failures,
                select_feedback_variant,
                stage_state.variant_indices,
                stagnation,
            )
        )
        if select_feedback_variant:
            assert detailed.placement is placement
            selected_variants = tuple(
                stage_problem.variant(strip, variant)
                for strip, variant in enumerate(stage_state.variant_indices)
            )
            requirement = projection_pitch_requirement(
                placement,
                instance_ids=stage_problem.instance_ids,
                variants=selected_variants,
                failure=projection_failures[0],
            )
            assert requirement is not None
            target = stage_problem.instance_ids.index(requirement.instance_id)
            feedback_variant = (
                target,
                variant_with_minimum_pitch(
                    selected_variants[target],
                    requirement.required_pitch,
                ),
            )
        if feedback_variant is None:
            return None
        target, padded = feedback_variant
        update = enable_variant_stage_boundary(
            stage_problem,
            stage_state,
            strip=target,
            variant=padded,
            select_variant=select_feedback_variant,
        )
        transform_updates.append((select_feedback_variant, update))
        return update

    detailed_results = iter(
        (
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), placement),
            DetailedStageResult(_routing(DetailedRouteStatus.BUDGET), None),
        )
    )

    solver = SequenceSolver(
        heights=(40,),
        problem_for_height=lambda _height: problem,
        adapters=StageAdapters(
            prepare=lambda _height, decoded: decoded,
            global_route=lambda _prepared, _feedback, _allowance: _global(),
            detailed_route=lambda _prepared, _allowance: next(detailed_results),
            validate=lambda _placement: ValidationVerdict(
                False,
                ("geom.collide",),
                None,
                (failure,),
            ),
        ),
        expansion_budget=budget,
        initial_states={40: state},
        config=config,
        stage_boundary_transform=transform,
    )
    sibling = solver._heights[0].restarts[1]
    sibling.anneal = replace(sibling.anneal, variant_indices=(1,))
    ordinary_sibling_id = problem.variant(0, 1).variant_id

    with pytest.raises(NoValidLayout):
        solver.search(max_stages=2)

    height_state = solver._heights[0]
    selected_update = next(update for select, update in transform_updates if select)
    sibling_update = next(update for select, update in transform_updates if not select)
    padded = selected_update.problem.variant(
        0,
        selected_update.state.variant_indices[0],
    )
    assert solver._incumbent is None
    assert padded.pitch_x == problem.variant(0, 0).pitch_x + 1
    assert selected_update.problem == sibling_update.problem == height_state.problem
    assert (
        sibling_update.problem.variant(0, sibling_update.state.variant_indices[0]).variant_id
        == ordinary_sibling_id
    )
    assert [select for _failures, select, _indices, _stagnation in transform_calls] == [
        True,
        False,
    ]
    assert height_state.stages == config.stages
    assert len(solver._stage_stats) == 2
    assert [stage.anneal_moves for stage in solver._stage_stats] == [
        0,
        config.moves_per_stage,
    ]
    assert all(stage.expansions == 0 for stage in solver._stage_stats)
    assert budget.spent == 0
    assert all(len(restart.archive) <= 3 for restart in height_state.restarts)
    observation = solver._stage_stats[0]
    assert observation.projection_failures == (failure,)
    assert isinstance(observation.pitch_requirement, ProjectionPitchRequirement)
    assert observation.pitch_requirement.required_pitch == padded.pitch_x
    assert solver._stage_stats[1].selected_variant_ids[0].placement_geometry[2] == padded.pitch_x


def test_different_strip_feedback_changes_only_unchanged_exact_relation() -> None:
    problem = PlacementProblem(
        sizes=((2, 2), (2, 2), (2, 2)),
        nets=(),
        outline_height=8,
        area_lower_bound=12,
    )
    state = AnnealState(
        pair=SequencePair((0, 1, 2), (0, 1, 2)),
        gaps=GapProfile.zero(3),
        base_seed=11,
        variant_indices=(0, 0, 0),
    )
    channels = (1, 1, 1)
    baseline = _decoded_pack(
        problem.outline_height,
        decode_state(problem, state),
        west_channels=channels,
    )
    geometries = (("variant-a",), ("variant-b",), ("variant-c",))
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (0, 1),
        "build colliders intersect",
        160,
    )
    no_good = finalize.ProjectionNoGood(
        left_strip=0,
        right_strip=1,
        delta_x=baseline.at[0][0] - baseline.at[1][0],
        delta_y=baseline.at[0][1] - baseline.at[1][1],
        pack_width=baseline.width,
        pack_height=baseline.height,
        left_origin=baseline.at[0],
        right_origin=baseline.at[1],
        left_geometry=geometries[0],
        right_geometry=geometries[1],
        failure=failure,
    )

    repaired = sequence_solver_module._projection_feedback_stage_update(
        problem,
        state,
        no_good,
        west_channels=channels,
        geometry_signatures=geometries,
        deadline=float("inf"),
        try_relation_update=True,
    )
    assert repaired is not None
    changed_pack = _decoded_pack(
        problem.outline_height,
        decode_state(problem, repaired.state),
        west_channels=channels,
    )
    assert (
        changed_pack.width,
        changed_pack.height,
        changed_pack.at[0],
        changed_pack.at[1],
    ) != (
        no_good.pack_width,
        no_good.pack_height,
        no_good.left_origin,
        no_good.right_origin,
    )

    already_changed = replace(
        state,
        gaps=GapProfile(east=(1, 0, 0), north=(0, 0, 0)),
    )
    unchanged = sequence_solver_module._projection_feedback_stage_update(
        problem,
        already_changed,
        no_good,
        west_channels=channels,
        geometry_signatures=geometries,
        deadline=float("inf"),
        try_relation_update=True,
    )
    assert unchanged == StageBoundaryUpdate(problem, already_changed)
    changed_geometry = sequence_solver_module._projection_feedback_stage_update(
        problem,
        state,
        no_good,
        west_channels=channels,
        geometry_signatures=(("variant-a-changed",), *geometries[1:]),
        deadline=float("inf"),
        try_relation_update=True,
    )
    assert changed_geometry == StageBoundaryUpdate(problem, state)


    exact = freeform_module.ExactPackNoGood(
        height=baseline.height,
        outline=problem.sizes,
        width=baseline.width,
        origins=tuple(baseline.at[index] for index in range(problem.size)),
        evidence=(failure,),
        projection_pair=freeform_module.ExactProjectionPair(
            left_strip=0,
            right_strip=1,
            left_geometry=geometries[0],
            right_geometry=geometries[1],
        ),
    )
    changed_exact_geometry = sequence_solver_module._projection_feedback_stage_update(
        problem,
        state,
        exact,
        west_channels=channels,
        geometry_signatures=(("variant-a-changed",), *geometries[1:]),
        deadline=float("inf"),
        try_relation_update=True,
    )
    assert changed_exact_geometry == StageBoundaryUpdate(problem, state)
    exact_repair = sequence_solver_module._projection_feedback_stage_update(
        problem,
        state,
        exact,
        west_channels=channels,
        geometry_signatures=geometries,
        deadline=float("inf"),
        try_relation_update=True,
    )
    assert exact_repair is not None
    exact_pack = _decoded_pack(
        problem.outline_height,
        decode_state(problem, exact_repair.state),
        west_channels=channels,
    )
    assert (
        exact_pack.height,
        exact_pack.width,
        tuple(exact_pack.at[index] for index in range(problem.size)),
    ) != (exact.height, exact.width, exact.origins)


def test_exact_projection_feedback_trials_stay_constant_for_many_strips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    size = 64
    problem = PlacementProblem(
        sizes=((2, 2),) * size,
        nets=(),
        outline_height=128,
        area_lower_bound=4 * size,
    )
    state = AnnealState(
        pair=SequencePair(tuple(range(size)), tuple(range(size))),
        gaps=GapProfile.zero(size),
        base_seed=19,
        variant_indices=(0,) * size,
    )
    channels = (1,) * size
    geometries = tuple((f"variant-{index}",) for index in range(size))
    baseline = _decoded_pack(
        problem.outline_height,
        decode_state(problem, state),
        west_channels=channels,
    )
    implicated = (17, 43)
    failure = finalize.ProjectionFailure(
        "geom.collide",
        implicated,
        "build colliders intersect",
        160,
    )
    exact = freeform_module.ExactPackNoGood(
        height=baseline.height,
        outline=problem.sizes,
        width=baseline.width,
        origins=tuple(baseline.at[index] for index in range(size)),
        evidence=(failure,),
        projection_pair=freeform_module.ExactProjectionPair(
            left_strip=implicated[0],
            right_strip=implicated[1],
            left_geometry=geometries[implicated[0]],
            right_geometry=geometries[implicated[1]],
        ),
    )
    original_decode = sequence_solver_module.decode_state
    decoded = 0

    def counted_decode(
        candidate_problem: PlacementProblem,
        candidate_state: AnnealState,
    ) -> DecodedPlacement:
        nonlocal decoded
        decoded += 1
        return original_decode(candidate_problem, candidate_state)

    monkeypatch.setattr(sequence_solver_module, "decode_state", counted_decode)
    repaired = sequence_solver_module._projection_feedback_stage_update(
        problem,
        state,
        exact,
        west_channels=channels,
        geometry_signatures=geometries,
        deadline=float("inf"),
        try_relation_update=True,
    )

    assert repaired is not None
    assert decoded == 2
    assert repaired.state.pair.positive == state.pair.positive
    assert {
        index
        for index, (before, after) in enumerate(
            zip(state.pair.negative, repaired.state.pair.negative, strict=True)
        )
        if before != after
    } == set(implicated)

    sibling = sequence_solver_module._projection_feedback_stage_update(
        problem,
        state,
        exact,
        west_channels=channels,
        geometry_signatures=geometries,
        deadline=float("inf"),
        try_relation_update=False,
    )
    assert sibling == StageBoundaryUpdate(problem, state)
    assert decoded == 3

    ownerless = replace(exact, projection_pair=None)
    expired = sequence_solver_module._projection_feedback_stage_update(
        problem,
        state,
        ownerless,
        west_channels=channels,
        geometry_signatures=geometries,
        deadline=time.monotonic() - 1.0,
        try_relation_update=True,
    )
    assert expired is None
    assert decoded == 3


def test_projection_pitch_feedback_single_restart_routes_padded_variant() -> None:
    problem, state, placement, failure = _projection_pitch_stage_fixture()
    padded = variant_with_minimum_pitch(
        problem.variant(0, 0),
        problem.variant(0, 0).pitch_x + 1,
    )
    detailed_results = iter(
        (
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), placement),
            DetailedStageResult(_routing(DetailedRouteStatus.BUDGET), None),
        )
    )

    def transform(
        _height: int,
        stage_problem: PlacementProblem,
        stage_state: AnnealState,
        _feedback: FeedbackState,
        _detailed: DetailedStageResult,
        _stagnation: int,
        _projection_failures: tuple[finalize.ProjectionFailure, ...],
        select_feedback_variant: bool,
    ) -> StageBoundaryUpdate:
        return enable_variant_stage_boundary(
            stage_problem,
            stage_state,
            strip=0,
            variant=padded,
            select_variant=select_feedback_variant,
        )

    solver = SequenceSolver(
        heights=(40,),
        problem_for_height=lambda _height: problem,
        adapters=StageAdapters(
            prepare=lambda _height, decoded: decoded,
            global_route=lambda _prepared, _feedback, _allowance: _global(),
            detailed_route=lambda _prepared, _allowance: next(detailed_results),
            validate=lambda _placement: ValidationVerdict(
                False,
                ("geom.collide",),
                None,
                (failure,),
            ),
        ),
        expansion_budget=ExpansionBudget(17),
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=32,
            restarts_per_height=1,
            global_elites=1,
        ),
        initial_states={40: state},
        stage_boundary_transform=transform,
    )

    with pytest.raises(NoValidLayout):
        solver.search(max_stages=2)

    assert solver._stage_stats[1].selected_variant_ids[0].placement_geometry[2] == 8


@pytest.mark.parametrize("borrow_first_discovery", [False, True])
def test_projection_pitch_feedback_runs_before_the_next_height_discovery(
    borrow_first_discovery: bool,
) -> None:
    problem, state, placement, failure = _projection_pitch_stage_fixture()
    padded = variant_with_minimum_pitch(
        problem.variant(0, 0),
        problem.variant(0, 0).pitch_x + 1,
    )
    validations = 0
    global_allowances: list[int] = []

    def global_route(
        _prepared: tuple[int, DecodedPlacement],
        _feedback: FeedbackState,
        allowance: int,
    ) -> GlobalRouteResult:
        global_allowances.append(allowance)
        return _global()


    def detailed_route(
        prepared: tuple[int, DecodedPlacement],
        _allowance: int,
    ) -> DetailedStageResult:
        height, _decoded = prepared
        if height != 40:
            return DetailedStageResult(_routing(DetailedRouteStatus.BUDGET), None)
        return DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), placement)

    def validate_projection(candidate: Placement) -> ValidationVerdict:
        nonlocal validations
        validations += 1
        if validations == 1:
            return ValidationVerdict(
                False,
                ("geom.collide",),
                None,
                (failure,),
            )
        return ValidationVerdict(
            True,
            (),
            replace(candidate, stats={"area": 1.0, "belt_tiles": 0.0}),
        )

    def transform(
        _height: int,
        stage_problem: PlacementProblem,
        stage_state: AnnealState,
        _feedback: FeedbackState,
        _detailed: DetailedStageResult,
        _stagnation: int,
        _projection_failures: tuple[finalize.ProjectionFailure, ...],
        select_feedback_variant: bool,
    ) -> StageBoundaryUpdate:
        return enable_variant_stage_boundary(
            stage_problem,
            stage_state,
            strip=0,
            variant=padded,
            select_variant=select_feedback_variant,
        )

    solver = SequenceSolver(
        heights=(40, 41),
        problem_for_height=lambda height: replace(problem, outline_height=height),
        adapters=StageAdapters(
            prepare=lambda height, decoded: (height, decoded),
            global_route=global_route,
            detailed_route=detailed_route,
            validate=validate_projection,
        ),
        expansion_budget=ExpansionBudget(17),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        stage_boundary_transform=transform,
        borrow_first_discovery=borrow_first_discovery,
    )
    solver._heights[0].restarts[0].anneal = state

    result = solver.search(max_stages=2)

    assert [stage.height for stage in result.stages] == [40, 40]
    assert result.stages[1].selected_variant_ids[0].placement_geometry[2] == 8
    assert bool(global_allowances) is not borrow_first_discovery


def test_routing_seed_projection_feedback_closes_only_the_protected_restart() -> None:
    problem, state, placement, failure = _projection_pitch_stage_fixture()
    padded = variant_with_minimum_pitch(
        problem.variant(0, 0),
        problem.variant(0, 0).pitch_x + 1,
    )
    validations = 0
    global_allowances: list[int] = []

    def global_route(
        _prepared: tuple[int, DecodedPlacement],
        _feedback: FeedbackState,
        allowance: int,
    ) -> GlobalRouteResult:
        global_allowances.append(allowance)
        return _global()

    def validate_projection(candidate: Placement) -> ValidationVerdict:
        nonlocal validations
        validations += 1
        if validations == 1:
            return ValidationVerdict(
                False,
                ("geom.collide",),
                None,
                (failure,),
            )
        return ValidationVerdict(
            True,
            (),
            replace(candidate, stats={"area": 1.0, "belt_tiles": 0.0}),
        )

    def transform(
        _height: int,
        stage_problem: PlacementProblem,
        stage_state: AnnealState,
        _feedback: FeedbackState,
        _detailed: DetailedStageResult,
        _stagnation: int,
        _projection_failures: tuple[finalize.ProjectionFailure, ...],
        select_feedback_variant: bool,
    ) -> StageBoundaryUpdate:
        return enable_variant_stage_boundary(
            stage_problem,
            stage_state,
            strip=0,
            variant=padded,
            select_variant=select_feedback_variant,
        )

    solver = SequenceSolver(
        heights=(40,),
        problem_for_height=lambda height: replace(problem, outline_height=height),
        adapters=StageAdapters(
            prepare=lambda height, decoded: (height, decoded),
            global_route=global_route,
            detailed_route=lambda _prepared, _allowance: DetailedStageResult(
                _routing(DetailedRouteStatus.ROUTED),
                placement,
            ),
            validate=validate_projection,
        ),
        expansion_budget=ExpansionBudget(17),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=2,
            global_elites=1,
        ),
        stage_boundary_transform=transform,
    )
    height_state = solver._heights[0]
    height_state.routing_seed = state

    result = solver.search(max_stages=2)

    assert [stage.height for stage in result.stages] == [40, 40]
    assert result.stages[1].selected_variant_ids[0].placement_geometry[2] == 8
    assert result.stages[1].anneal_seeds == (height_state.restarts[0].seed,)
    assert global_allowances == []
    assert solver.budget.discovery_complete


@pytest.mark.parametrize("closure_allowance", [None, 0])
def test_zero_budget_projection_feedback_preserves_stage_and_marker(
    closure_allowance: int | None,
) -> None:
    problem, state, _placement, _failure = _projection_pitch_stage_fixture()
    detailed_allowances: list[int] = []

    def detailed_route(
        _decoded: DecodedPlacement,
        allowance: int,
    ) -> DetailedStageResult:
        detailed_allowances.append(allowance)
        return DetailedStageResult(_routing(DetailedRouteStatus.BUDGET), None)

    solver = SequenceSolver(
        heights=(40,),
        problem_for_height=lambda _height: problem,
        adapters=StageAdapters(
            prepare=lambda _height, decoded: decoded,
            global_route=lambda _prepared, _feedback, _allowance: _global(),
            detailed_route=detailed_route,
            validate=lambda _placement: pytest.fail("zero-budget feedback validated"),
        ),
        expansion_budget=ExpansionBudget(17),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )
    height_state = solver._heights[0]
    restart = height_state.restarts[0]
    restart.anneal = state
    restart.stages = 1
    height_state.feedback_restart = restart.restart

    assert solver._run_pending_projection_feedback(
        height_state,
        0,
        1,
        prior_cancelled=False,
        closure_allowance=closure_allowance,
    ) == (0, False)
    assert detailed_allowances == []
    assert restart.stages == 1
    assert height_state.feedback_restart == restart.restart


def test_production_padded_variant_transform_maps_same_strip_projection() -> None:
    problem, state, placement, failure = _projection_pitch_stage_fixture()
    run = _production_run(
        projected_chemical_plant_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=2,
        config=SequenceSolverConfig.test(),
    )
    transform = run.solver.stage_boundary_transform
    assert transform is not None
    alternate_state = replace(state, variant_indices=(1,))
    detailed = DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), placement)

    selected = transform(
        40,
        problem,
        state,
        FeedbackState.empty((40, 40)),
        detailed,
        0,
        (failure,),
        True,
    )
    sibling = transform(
        40,
        problem,
        alternate_state,
        FeedbackState.empty((40, 40)),
        detailed,
        0,
        (failure,),
        False,
    )

    assert selected is not None
    assert sibling is not None
    assert selected.problem == sibling.problem
    assert selected.problem.variant(0, selected.state.variant_indices[0]).pitch_x == 8
    assert (
        sibling.problem.variant(0, sibling.state.variant_indices[0]).variant_id
        == problem.variant(0, alternate_state.variant_indices[0]).variant_id
    )


def test_projection_pitch_unmapped_control_does_not_enable_padded_variant() -> None:
    problem, state, placement, failure = _projection_pitch_stage_fixture()
    run = _production_run(
        projected_chemical_plant_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=2,
        config=SequenceSolverConfig.test(),
    )
    transform = run.solver.stage_boundary_transform
    assert transform is not None
    buildings = list(placement.buildings)
    buildings[1] = replace(buildings[1], owner_strip=None)
    detailed = DetailedStageResult(
        _routing(DetailedRouteStatus.ROUTED),
        replace(placement, buildings=tuple(buildings)),
    )

    assert (
        transform(
            40,
            problem,
            state,
            FeedbackState.empty((40, 40)),
            detailed,
            0,
            (failure,),
            True,
        )
        is None
    )
    selected_pitches = {
        problem.variant(strip, variant).pitch_x
        for strip, variant in enumerate(state.variant_indices)
    }
    assert selected_pitches == {7}


@pytest.mark.parametrize("independent", [True, False])
def test_different_strip_feedback_rebuilds_production_stage(
    monkeypatch: pytest.MonkeyPatch,
    independent: bool,
) -> None:
    problem, state, placement, failure = _projection_pitch_stage_fixture()
    run = _production_run(
        projected_chemical_plant_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=2,
        config=SequenceSolverConfig.test(),
    )
    transform = run.solver.stage_boundary_transform
    assert transform is not None
    second_instance = replace(problem.instance_ids[0], machine_start=2)
    problem = replace(
        problem,
        sizes=problem.sizes + problem.sizes,
        instance_ids=problem.instance_ids + (second_instance,),
        variant_tables=problem.variant_tables + problem.variant_tables,
    )
    state = AnnealState.initial(2, seed=17)
    buildings = list(placement.buildings)
    buildings.extend(
        replace(building, x=building.x + 20, owner_strip=1)
        for building in placement.buildings
    )
    failure = replace(failure, buildings=(0, 2))
    detailed = DetailedStageResult(
        _routing(DetailedRouteStatus.ROUTED),
        replace(placement, buildings=tuple(buildings)),
    )
    monkeypatch.setattr(
        finalize,
        "independent_projection_pair",
        lambda pair, _policy, **_kwargs: (
            tuple(index for index, _building in pair) if independent else None
        ),
    )

    selected = transform(
        40,
        problem,
        state,
        FeedbackState.empty((40, 40)),
        detailed,
        0,
        (failure,),
        True,
    )

    assert selected is not None
    assert selected.problem == problem
    assert selected.state != state
    sibling = transform(
        40,
        problem,
        selected.state,
        FeedbackState.empty((40, 40)),
        detailed,
        0,
        (failure,),
        False,
    )
    assert sibling == StageBoundaryUpdate(problem, selected.state)


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
        detailed: DetailedStageResult,
        stagnation: int,
        _projection_failures: tuple[finalize.ProjectionFailure, ...],
        _select_feedback_variant: bool,
    ) -> StageBoundaryUpdate | None:
        transformed_stagnation.append(stagnation)
        target = select_split_candidate(
            detailed.routing,
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
            validate=lambda _placement: ValidationVerdict(False, ("unreachable",), None),
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


def test_production_boundary_does_not_merge_incompatible_or_implicated_children() -> None:
    family = next(
        candidate
        for candidate in generate_strip_families(two_stage_spec())
        if candidate.total_machine_count > 1 and len(candidate.variants) > 1
    )
    (parent,) = partition_strip_family(
        family,
        max_machine_count=family.total_machine_count,
    )
    variants = variants_for_count(family, family.total_machine_count)
    problem = PlacementProblem(
        sizes=((variants[0].box_width, variants[0].box_height),),
        nets=((0, 0),),
        outline_height=40,
        area_lower_bound=1,
        instance_ids=(parent.instance_id,),
        variant_tables=(variants,),
    )
    state = AnnealState.initial(1, seed=19)
    unimplicated = DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(
            NetFailure(
                NetId(None, None, "elsewhere", NetRole.INTERNAL, 0),
                RouteFailureKind.CONGESTION_WALL,
                ((0, 0, 0),),
                (),
                0,
            ),
        ),
        iterations=1,
        expansions=0,
    )
    implicated = _routing(
        DetailedRouteStatus.STRANDED,
        geometric_failure=True,
    )
    incompatible = split_stage_boundary(
        problem,
        state,
        family,
        0,
        right_variant_offset=1,
    )
    compatible = split_stage_boundary(problem, state, family, 0)

    assert (
        _pose_stage_boundary_update(
            incompatible.problem,
            incompatible.state,
            unimplicated,
            stagnation=1,
            family_by_id={family.family_id: family},
        )
        is None
    )
    assert (
        _pose_stage_boundary_update(
            compatible.problem,
            compatible.state,
            implicated,
            stagnation=1,
            family_by_id={family.family_id: family},
        )
        is None
    )


def test_topology_change_clears_stale_quality_archives_before_restart_fallback() -> None:
    original = PlacementProblem(
        sizes=((1, 1),),
        nets=((0, 0),),
        outline_height=40,
        area_lower_bound=1,
    )
    rebuilt = PlacementProblem(
        sizes=((1, 1), (1, 1)),
        nets=((0, 1),),
        outline_height=40,
        area_lower_bound=2,
    )
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(
                _routing(DetailedRouteStatus.STRANDED, geometric_failure=True),
                None,
            ),
        )
    )

    def transform(
        _height: int,
        _problem: PlacementProblem,
        state: AnnealState,
        _feedback: FeedbackState,
        _detailed: DetailedStageResult,
        _stagnation: int,
        _projection_failures: tuple[finalize.ProjectionFailure, ...],
        _select_feedback_variant: bool,
    ) -> StageBoundaryUpdate:
        return StageBoundaryUpdate(
            rebuilt,
            AnnealState(
                pair=SequencePair((0, 1), (0, 1)),
                gaps=GapProfile.zero(2),
                base_seed=state.base_seed,
                stage_index=state.stage_index,
                variant_indices=(0, 0),
            ),
        )

    solver = SequenceSolver(
        heights=(40,),
        problem_for_height=lambda _height: original,
        adapters=fake.adapters(),
        expansion_budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=2,
            global_elites=1,
        ),
        stage_boundary_transform=transform,
    )
    seeds = tuple(restart.seed for restart in solver._heights[0].restarts)

    with pytest.raises(NoValidLayout):
        solver.search(max_stages=1)

    height_state = solver._heights[0]
    assert height_state.problem == rebuilt
    assert all(not restart.archive for restart in height_state.restarts)
    assert height_state.quality_restart is None
    accepted_after_rebuild = tuple(restart.accepted_moves for restart in height_state.restarts)
    height_state.objective_mode = sequence_solver_module.ObjectiveMode.QUALITY
    height_state.quality_restart = 1

    with pytest.raises(NoValidLayout):
        solver.search(max_stages=2)

    resumed = solver._stage_stats[1]
    assert resumed.global_routes == 1
    assert resumed.quality_exited
    assert resumed.objective_mode is sequence_solver_module.ObjectiveMode.EXPLORATION
    assert len(fake.prepared_candidates[-1][1].x) == 2
    assert tuple(restart.seed for restart in height_state.restarts) == seeds
    assert tuple(restart.stages for restart in height_state.restarts) in {
        (2, 1),
        (1, 2),
    }
    assert all(
        after >= before
        for before, after in zip(
            accepted_after_rebuild,
            (restart.accepted_moves for restart in height_state.restarts),
            strict=True,
        )
    )


def test_exact_problem_identity_transform_retains_restart_archive() -> None:
    problem = PlacementProblem(
        sizes=((1, 1),),
        nets=((0, 0),),
        outline_height=40,
        area_lower_bound=1,
    )
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(
                _routing(DetailedRouteStatus.STRANDED, geometric_failure=True),
                None,
            ),
        )
    )

    def identity_transform(
        _height: int,
        stage_problem: PlacementProblem,
        state: AnnealState,
        _feedback: FeedbackState,
        _detailed: DetailedStageResult,
        _stagnation: int,
        _projection_failures: tuple[finalize.ProjectionFailure, ...],
        _select_feedback_variant: bool,
    ) -> StageBoundaryUpdate:
        return StageBoundaryUpdate(stage_problem, state)

    solver = SequenceSolver(
        heights=(40,),
        problem_for_height=lambda _height: problem,
        adapters=fake.adapters(),
        expansion_budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        stage_boundary_transform=identity_transform,
    )

    with pytest.raises(NoValidLayout):
        solver.search(max_stages=1)

    assert solver._heights[0].restarts[0].archive


def test_fixed_size_problem_skips_pose_boundary_transforms_without_metadata() -> None:
    problem = PlacementProblem(
        sizes=((1, 1), (1, 1)),
        nets=(),
        outline_height=40,
        area_lower_bound=2,
    )
    geometric_failure = DetailedRouteResult(
        status=DetailedRouteStatus.STRANDED,
        routed=(),
        failures=(
            NetFailure(
                NetId(None, None, "external", NetRole.INTERNAL, 0),
                RouteFailureKind.CONGESTION_WALL,
                ((0, 0, 0),),
                (),
                0,
            ),
        ),
        iterations=1,
        expansions=0,
    )
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(geometric_failure, None),),
    )
    boundary_updates: list[StageBoundaryUpdate | None] = []

    def boundary(
        _height: int,
        stage_problem: PlacementProblem,
        stage_state: AnnealState,
        _feedback: FeedbackState,
        detailed: DetailedStageResult,
        stagnation: int,
        _projection_failures: tuple[finalize.ProjectionFailure, ...],
        _select_feedback_variant: bool,
    ) -> StageBoundaryUpdate | None:
        update = _pose_stage_boundary_update(
            stage_problem,
            stage_state,
            detailed.routing,
            stagnation=stagnation,
            family_by_id={},
        )
        boundary_updates.append(update)
        return update

    solver = SequenceSolver(
        heights=(40,),
        problem_for_height=lambda _height: problem,
        adapters=fake.adapters(),
        expansion_budget=ExpansionBudget(100),
        config=SequenceSolverConfig(
            stages=2,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
        stage_boundary_transform=boundary,
    )

    with pytest.raises(NoValidLayout):
        solver.search(max_stages=2)

    assert boundary_updates == [None, None]
    assert len(fake.detailed_allowances) == 2
    assert solver._heights[0].problem == problem


def test_sequence_backend_returns_authoritative_finalized_placement_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    policy = BandPolicy("portable")
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    production = _production_run(
        spec,
        band_policy=policy,
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    routed = _placement(area=10, belt_tiles=2)
    fake = _FakeRouting(
        detailed_results=(DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), routed),)
    )
    def global_route(
        prepared: _ProductionCandidate,
        feedback: FeedbackState,
        allowance: int,
    ) -> GlobalRouteResult:
        return fake.global_route((prepared.height, prepared.decoded), feedback, allowance)

    def detailed_route(
        prepared: _ProductionCandidate,
        allowance: int,
    ) -> DetailedStageResult:
        return fake.detailed_route((prepared.height, prepared.decoded), allowance)

    production.solver.adapters = replace(
        production.solver.adapters,
        global_route=global_route,
        detailed_route=detailed_route,
    )
    serial_run = replace(
        production,
        max_search_stages=1,
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_production_run",
        lambda *_args, **_kwargs: serial_run,
    )
    finalized: list[Placement] = []
    finalize_placement = finalize.finalize_placement

    def track_finalization(placement: Placement, band_policy: BandPolicy) -> Placement:
        result = finalize_placement(placement, band_policy)
        finalized.append(result)
        return result

    monkeypatch.setattr(finalize, "finalize_placement", track_finalization)

    placement = SequencePairLayout(
        band_policy=policy,
        config=SequenceSolverConfig.test(),
    ).lay_out(spec, time_budget_s=2.0)

    assert len(finalized) == 1
    assert placement == replace(
        finalized[0],
        completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
    )
    assert placement.completion is PlacementCompletion.COMPACTED_AND_FINALIZED


def test_sequence_completion_compacts_then_finalizes_then_validates_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    policy = BandPolicy("portable")
    production = _production_run(
        spec,
        band_policy=policy,
        time_budget_s=20.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    routed = _placement(area=10, belt_tiles=2)
    compacted = _placement(area=9, belt_tiles=1)
    projected = replace(
        _placement(area=8, belt_tiles=1),
        frame=AreaFrame(
            width=8,
            height=1,
            primary_band=40,
            certified_bands=(40,),
            rotated=False,
        ),
    )
    trace: list[tuple[str, Placement]] = []

    def compact(
        candidate: Placement,
        *_args: object,
        **_kwargs: object,
    ) -> finalize.BoundaryCompactionResult:
        trace.append(("compact", candidate))
        return finalize.BoundaryCompactionResult(compacted, validate.Report(findings=()))

    def project(
        candidate: Placement,
        *_args: object,
        **_kwargs: object,
    ) -> Placement:
        trace.append(("finalize", candidate))
        return projected

    def certify(
        candidate: Placement,
        *_args: object,
        **_kwargs: object,
    ) -> validate.Report:
        trace.append(("validate", candidate))
        return validate.Report(findings=())

    monkeypatch.setattr(finalize, "compact_open_boundary_belts_certified", compact)
    monkeypatch.setattr(finalize, "finalize_placement", project)
    monkeypatch.setattr(validate, "certify", certify)

    verdict = production.solver.adapters.validate(routed)

    assert verdict.ok
    assert verdict.placement == replace(
        projected,
        completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
    )
    assert trace == [
        ("compact", routed),
        ("finalize", compacted),
        ("validate", projected),
    ]

def test_sequence_completion_cancels_projection_before_atomic_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=20.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    expired = False
    validated = False

    def monotonic() -> float:
        return float("inf") if expired else 0.0

    def compact(
        *_args: object,
        cancelled: Callable[[], bool],
        **_kwargs: object,
    ) -> Never:
        nonlocal expired
        expired = True
        assert cancelled()
        raise finalize.ProjectionCancelled

    def certify(*_args: object, **_kwargs: object) -> validate.Report:
        nonlocal validated
        validated = True
        return validate.Report(findings=())

    monkeypatch.setattr(sequence_solver_module.time, "monotonic", monotonic)
    monkeypatch.setattr(finalize, "compact_open_boundary_belts_certified", compact)
    monkeypatch.setattr(validate, "certify", certify)

    verdict = production.solver.adapters.validate(_placement(area=10, belt_tiles=2))

    assert not verdict.ok
    assert verdict.status is DetailedRouteStatus.BUDGET
    assert not validated


def test_first_topology_candidate_reuses_only_a_width_admissible_hint() -> None:
    candidate = CompactTopologyCandidate(
        topology_index=0,
        status=CompactSeedStatus.FEASIBLE,
        x=(0,),
        y=(0,),
        width=10,
        used_height=1,
        variant_indices=(0,),
        signature=PairwiseRelationSignature(()),
        deterministic_time=0.1,
    )
    hint = DecodedPlacement(
        x=(10,),
        y=(0,),
        width=11,
        used_height=1,
        x_windows=((10, 10),),
        y_windows=((0, 0),),
        gap_area=0,
        variant_indices=(0,),
    )

    assert sequence_solver_module._topology_close_decoded(candidate, hint) is hint
    assert (
        sequence_solver_module._topology_close_decoded(
            replace(candidate, width=9),
            hint,
        )
        is not hint
    )
    assert (
        sequence_solver_module._topology_close_decoded(
            replace(candidate, topology_index=1),
            hint,
        )
        is not hint
    )


@pytest.mark.parametrize("belt_vertical_construction", [False, True])
def test_sequence_backend_returns_only_certified_powered_placements(
    belt_vertical_construction: bool,
) -> None:
    spec = two_stage_spec()
    placement = SequencePairLayout(
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=belt_vertical_construction,
        config=SequenceSolverConfig.test(),
    ).lay_out(spec, time_budget_s=2.0)

    assert not validate.validate(
        placement,
        spec,
        ids=validate.id_map(spec),
        expect_power=True,
        belt_vertical_construction=belt_vertical_construction,
    ).errors
    backend: object = placement.stats["backend"]
    assert backend == "sequence-pair"
    assert placement.stats["detailed_routes"] >= 1.0
    assert placement.stats["direct_candidates"] == 1.0
    assert 0.0 <= placement.stats["direct_inserts"] <= 1.0
    assert placement.stats["power"] == 1.0
    assert placement.stats["towers"] > 0.0
    assert {
        "seeds",
        "seed",
        "accelerator",
        "heights",
        "restarts",
        "stages",
        "anneal_stages",
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
        "archive_category",
        "archive_categories",
        "objective_mode",
        "global_skip_reason",
        "quality_stages",
        "quality_entries",
        "quality_exits",
        "global_skips",
        "max_quality_stagnation",
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
        "pack_width",
        "target_height",
        "used_height",
        "box_area",
        "gap_area",
        "weighted_hpwl",
        "history_cost",
        "missed_direct_inserts",
        "hard_outline_overflow",
        "search_energy",
    } <= placement.stats.keys()


def test_production_observability_preserves_categories_and_all_grouped_work() -> None:
    exact_seed = 9007199254740993
    config = SequenceSolverConfig(
        stages=2,
        moves_per_stage=1,
        restarts_per_height=2,
        global_elites=1,
        global_rounds=1,
        seed=exact_seed,
    )
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=config,
    )

    # This test audits every grouped stage; production's safe early stop is not
    # the behavior under test.
    run.solver.stop_on_stable_exact = False
    result = run.solver.search()
    original_stats = dict(result.placement.stats)
    placement = sequence_solver_module._with_observational_stats(
        result,
        run,
        False,
        config,
    )
    cython_accelerator: object = placement.stats["accelerator"]
    assert cython_accelerator == "cython"
    assert type(placement.stats["seed"]) is int
    assert placement.stats["seed"] == exact_seed
    assert json.loads(json.dumps(placement.stats))["seed"] == exact_seed
    assert {stage.backend for stage in result.stages} == {"cython"}

    python_result = replace(
        result,
        stages=tuple(replace(stage, backend="python") for stage in result.stages),
    )
    python_placement = sequence_solver_module._with_observational_stats(
        python_result,
        run,
        False,
        config,
    )
    python_accelerator: object = python_placement.stats["accelerator"]
    assert python_accelerator == "python"

    assert len(result.stages) > 1
    mixed_result = replace(
        result,
        stages=(replace(result.stages[0], backend="python"), *result.stages[1:]),
    )
    assert {stage.backend for stage in mixed_result.stages} == {"python", "cython"}
    mixed_placement = sequence_solver_module._with_observational_stats(
        mixed_result,
        run,
        False,
        config,
    )
    mixed_accelerator: object = mixed_placement.stats["accelerator"]
    assert mixed_accelerator == "mixed"

    discovery = tuple(stage for stage in result.stages if stage.anneal_stages == 2)
    executed_global = tuple(stage for stage in result.stages if stage.global_routes > 0)
    skipped_global = tuple(
        stage for stage in result.stages if stage.global_skip_reason == "quality-mode"
    )
    all_restarts = tuple(restart for height in run.solver._heights for restart in height.restarts)
    all_stage_seeds = {seed for stage in result.stages for seed in stage.anneal_seeds}

    assert len(discovery) == len(run.heights)
    assert all(stage.anneal_moves == 2 for stage in discovery)
    assert all(len(stage.anneal_seeds) == 2 for stage in discovery)
    assert sum(stage.anneal_moves for stage in result.stages) == sum(
        restart.stages * config.moves_per_stage for restart in all_restarts
    )
    assert sum(stage.accepted_moves for stage in result.stages) == sum(
        restart.accepted_moves for restart in all_restarts
    )
    assert all_stage_seeds == {restart.seed for restart in all_restarts}
    assert placement.stats["stages"] == float(len(result.stages))
    assert placement.stats["anneal_stages"] == float(
        sum(stage.anneal_stages for stage in result.stages)
    )
    assert placement.stats["moves"] == float(sum(stage.anneal_moves for stage in result.stages))
    assert placement.stats["accepted_moves"] == float(
        sum(stage.accepted_moves for stage in result.stages)
    )
    assert placement.stats["seeds"] == float(len(all_stage_seeds))

    assert result.exact_archive_categories
    expected_categories = [category.value for category in result.exact_archive_categories]
    archive_categories: object = placement.stats["archive_categories"]
    archive_category: object = placement.stats["archive_category"]
    assert archive_categories == expected_categories
    assert archive_category == expected_categories[0]
    exact_stage = next(
        stage
        for stage in result.stages
        if stage.exact_key == result.exact_key and stage.candidate_key == result.exact_candidate_key
    )
    assert exact_stage.archive_categories == result.exact_archive_categories

    assert executed_global
    assert skipped_global
    assert all(stage.global_route_time_s > 0.0 for stage in executed_global)
    assert all(stage.global_route_time_s == 0.0 for stage in skipped_global)
    for stage in result.stages:
        assert stage.preparation_time_s >= 0.0
        assert stage.global_route_time_s >= 0.0
        assert stage.detailed_route_time_s >= 0.0
        assert stage.validation_time_s >= 0.0
    for field_name in (
        "preparation_time_s",
        "global_route_time_s",
        "detailed_route_time_s",
        "validation_time_s",
    ):
        assert placement.stats[field_name] == sum(
            getattr(stage, field_name) for stage in result.stages
        )
    assert placement.stats["total_time_s"] == pytest.approx(
        placement.stats["planning_time_s"]
        + placement.stats["placement_time_s"]
        + placement.stats["preparation_time_s"]
        + placement.stats["global_route_time_s"]
        + placement.stats["detailed_route_time_s"]
        + placement.stats["validation_time_s"]
        + placement.stats["compilation_time_s"]
    )

    final_stats = dict(result.placement.stats)
    assert all(final_stats[key] == value for key, value in original_stats.items())
    assert result.placement is placement is python_placement is mixed_placement
    assert result.exact_candidate_key == exact_stage.candidate_key


def test_sequence_reuses_adaptive_coarse_strip_partition_before_problem_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = BandPolicy("120")
    coarse_replans: list[tuple[int, BandPolicy]] = []
    real_plan_strips = freeform_module.plan_strips
    unit = Fraction(1)
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=240,
                inputs_per_machine={"iron-ore": unit},
                outputs_per_machine={"iron-ingot": unit},
            ),
        ),
        external_inputs={"iron-ore": Fraction(240)},
        outputs={"iron-ingot": Fraction(240)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=Fraction(30),
        label="coarse-sequence-partition",
    )
    fine = plan_strips(spec, strip_len=6, band_policy=policy)
    assert len(fine) == 40

    def track_coarse_replan(
        selected_spec: BuildSpec,
        *,
        strip_len: int = 6,
        band_policy: BandPolicy = BandPolicy("portable"),
        **kwargs: object,
    ) -> list[freeform_module.Strip]:
        coarse_replans.append((strip_len, band_policy))
        return real_plan_strips(
            selected_spec,
            strip_len=strip_len,
            band_policy=band_policy,
            **kwargs,
        )

    monkeypatch.setattr(freeform_module, "plan_strips", track_coarse_replan)

    run = _production_run(
        spec,
        band_policy=policy,
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    problem = run.solver._heights[0].problem

    assert problem.size == 1
    assert sum(instance.machine_count for instance in problem.instance_ids) == 240
    assert {instance.family_id for instance in problem.instance_ids} == {
        strip.family_id for strip in fine
    }
    assert coarse_replans == [(spec.machine_count, policy)]


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

    placement = SequencePairLayout(
        band_policy=BandPolicy("portable"),
        config=SequenceSolverConfig.test()
    ).lay_out(
        spec,
        time_budget_s=2.0,
    )

    refinery = next(building for building in placement.buildings if building.item_id == 2308)
    assert refinery.yaw in {90.0, 270.0}
    assert not validate.certify(placement, spec, expect_power=True).errors
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

    placement = SequencePairLayout(
        band_policy=BandPolicy("portable"),
        config=SequenceSolverConfig.test()
    ).lay_out(
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

    placement = SequencePairLayout(
        band_policy=BandPolicy("portable"),
        config=SequenceSolverConfig.test()
    ).lay_out(
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


def test_port_docked_output_has_stable_sequence_variant_identity() -> None:
    spec = ray_receiver_spec()
    first = generate_strip_families(spec)
    second = generate_strip_families(spec)
    receiver = next(family for family in first if family.machine_item_id == catalog.RAY_RECEIVER_ID)

    assert receiver.variants
    assert tuple(variant.variant_id for variant in receiver.variants) == tuple(
        variant.variant_id
        for family in second
        if family.family_id == receiver.family_id
        for variant in family.variants
    )
    for variant in receiver.variants:
        assert variant.attachment_plan == ()
        assert len(variant.port_dock_plan) == 1
        dock = variant.port_dock_plan[0]
        assert dock.lane == receiver.output_lanes[0]
        assert dock.lane_y == variant.lane_plan.row_for(dock.lane.lane_id)
        assert dock.facing.delta[1] > 0
        assert dock.cell[1] < dock.lane_y
        assert variant.variant_id.port_docks == (dock.identity,)


def test_selected_port_variant_reaches_shared_prepared_docking_geometry() -> None:
    spec = ray_receiver_spec()
    strips = plan_strips(spec)
    instance_ids, variant_tables = _variant_search_inputs(spec, strips, strip_len=6)
    problem = PlacementProblem(
        sizes=tuple(_box(strip) for strip in strips),
        nets=tuple(_nets_between(strips)),
        outline_height=sum(_box(strip)[1] for strip in strips),
        area_lower_bound=sum(width * height for width, height in map(_box, strips)),
        instance_ids=instance_ids,
        variant_tables=variant_tables,
    )
    selected = _selected_strips(
        strips,
        problem,
        (0,) * problem.size,
        band_policy=BandPolicy("portable"),
    )
    receiver_index, receiver = next(
        (index, strip)
        for index, strip in enumerate(selected)
        if strip.item_id == catalog.RAY_RECEIVER_ID
    )
    pack = _greedy_pack(selected, problem.outline_height)

    prepared = _prepare_routing_problem(
        spec,
        selected,
        pack,
        policy=BandPolicy("portable"),
        power=False
    )
    docks = [
        building
        for building in prepared.building_templates
        if catalog.is_belt(building.item_id)
        and building.input_obj is not None
        and prepared.building_templates[building.input_obj].item_id == catalog.RAY_RECEIVER_ID
    ]

    assert receiver.port_dock_plan == problem.variant(receiver_index, 0).port_dock_plan
    assert (
        _selected_direct_targets(
            spec,
            strips,
            problem,
            (0,) * problem.size,
            band_policy=BandPolicy("portable"),
        )
        == ()
    )
    assert len(docks) == receiver.machines
    assert all(dock.input_to_slot == rules.BELT_PORT_DRAW_TO_SLOT for dock in docks)
    assert {dock.input_from_slot for dock in docks} == {receiver.port_dock_plan[0].port}


def test_sequence_preparation_consumes_elevated_machine_and_tesla_junction_bans() -> None:
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=True,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    height = run.heights[0]
    problem = run.solver._heights[0].problem
    candidate = run.solver.adapters.prepare(
        height,
        decode_state(
            problem,
            AnnealState.initial(problem.size, run.solver.config.seed),
        ),
    )
    assert candidate.prepared is not None
    prepared = candidate.prepared
    workspace = prepared.new_workspace()
    static_buildings = tuple(
        building
        for building in prepared.building_templates
        if not catalog.is_belt(building.item_id)
        and not catalog.is_sorter(building.item_id)
    )
    transport_buildings = tuple(
        building
        for building in prepared.building_templates
        if catalog.is_belt(building.item_id) or catalog.is_sorter(building.item_id)
    )
    machine_ban = freeform_module._prepared_junction_ban(static_buildings, ())
    tesla_ban = freeform_module._prepared_junction_ban((), prepared.power_sites)
    expected_ban = machine_ban | tesla_ban

    assert machine_ban
    assert tesla_ban
    assert any(level > 0 for _x, _y, level in machine_ban)
    assert any(level > 0 for _x, _y, level in tesla_ban)
    assert freeform_module._prepared_junction_ban(transport_buildings, ()) == frozenset()
    assert prepared.junction_ban == expected_ban
    assert workspace.canvas.junction_geometry_prepared
    assert workspace.canvas.junction_ban == set(expected_ban)


def test_ray_receiver_sequence_closed_loop_routes_and_validates_exactly() -> None:
    spec = ray_receiver_spec()

    placement = SequencePairLayout(
        band_policy=BandPolicy("portable"),
        config=SequenceSolverConfig.test()
    ).lay_out(
        spec,
        time_budget_s=2.0,
    )
    docks = [
        building
        for building in placement.buildings
        if catalog.is_belt(building.item_id)
        and building.input_obj is not None
        and placement.buildings[building.input_obj].item_id == catalog.RAY_RECEIVER_ID
    ]

    assert len(docks) == 2
    assert not validate.certify(placement, spec, expect_power=True).errors


@pytest.mark.slow
def test_sequence_pair_plastic_projection_pitch_feedback_finalizes_cleanly() -> None:
    spec = plastic_spec()
    policy = BandPolicy("portable")

    placement = SequencePairLayout(
        band_policy=policy,
        islands=1,
    ).lay_out(
        spec,
        time_budget_s=4.0,
    )

    assert validate.certify(placement, spec, expect_power=True).ok
    finalize.finalize_placement(placement, policy)
    chemical_by_owner: dict[int, list[PlacedBuilding]] = {}
    for building in placement.buildings:
        if building.item_id == 2309 and type(building.owner_strip) is int:
            chemical_by_owner.setdefault(building.owner_strip, []).append(building)
    selected_pitches = {
        right.x - left.x
        for buildings in chemical_by_owner.values()
        for left, right in zip(
            sorted(buildings, key=lambda building: building.x),
            sorted(buildings, key=lambda building: building.x)[1:],
            strict=False,
        )
    }

    assert selected_pitches == {8}


@pytest.mark.slow
def test_sequence_pair_routes_self_consuming_pinned_flow(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    placement = SequencePairLayout(
        band_policy=BandPolicy("portable"),
        islands=1,
    ).lay_out(
        refined_oil_feedback_spec,
        time_budget_s=15.0,
    )
    assert validate.certify(
        placement,
        refined_oil_feedback_spec,
        expect_power=True,
    ).ok


def test_production_forwards_fixed_band_through_initial_compact_and_coarsen_plans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = BandPolicy("120")
    plan_calls: list[tuple[int, BandPolicy]] = []
    coarsen_calls: list[BandPolicy] = []
    real_plan_strips = sequence_solver_module.plan_strips
    real_coarsen = sequence_solver_module._coarsen_saturated_strip_plan

    def track_plan(
        spec: BuildSpec,
        *,
        strip_len: int = 6,
        band_policy: BandPolicy = BandPolicy("portable"),
        **kwargs: object,
    ) -> list[freeform_module.Strip]:
        plan_calls.append((strip_len, band_policy))
        return real_plan_strips(
            spec,
            strip_len=strip_len,
            band_policy=band_policy,
            **kwargs,
        )

    def track_coarsen(
        spec: BuildSpec,
        strips: list[freeform_module.Strip],
        *,
        strip_len: int,
        band_policy: BandPolicy = BandPolicy("portable"),
        **kwargs: object,
    ) -> tuple[list[freeform_module.Strip], int]:
        coarsen_calls.append(band_policy)
        return real_coarsen(
            spec,
            strips,
            strip_len=strip_len,
            band_policy=band_policy,
            **kwargs,
        )

    monkeypatch.setattr(sequence_solver_module, "plan_strips", track_plan)
    monkeypatch.setattr(
        sequence_solver_module,
        "_coarsen_saturated_strip_plan",
        track_coarsen,
    )
    monkeypatch.setattr(sequence_solver_module, "_MID_NO_SPRAY_COMPACT_MIN_MACHINES", 0)
    monkeypatch.setattr(
        sequence_solver_module,
        "_MID_NO_SPRAY_COMPACT_MAX_MACHINES",
        10**9,
    )
    monkeypatch.setattr(sequence_solver_module, "_MID_NO_SPRAY_COMPACT_MIN_STRIPS", 0)
    monkeypatch.setattr(
        sequence_solver_module,
        "_MID_NO_SPRAY_COMPACT_MAX_STRIPS",
        10**9,
    )

    _production_run(
        two_stage_spec(),
        band_policy=policy,
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )

    assert plan_calls == [(6, policy), (4, policy)]
    assert coarsen_calls == [policy]


def test_production_forwards_fixed_band_through_fallback_replan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    policy = BandPolicy("120")
    plan_calls: list[tuple[int, BandPolicy]] = []
    real_plan_strips = sequence_solver_module.plan_strips

    def fail_once_then_plan(
        selected_spec: BuildSpec,
        *,
        strip_len: int = 6,
        band_policy: BandPolicy = BandPolicy("portable"),
        **kwargs: object,
    ) -> list[freeform_module.Strip]:
        plan_calls.append((strip_len, band_policy))
        if len(plan_calls) == 1:
            raise ValueError("force production fallback")
        return real_plan_strips(
            selected_spec,
            strip_len=strip_len,
            band_policy=band_policy,
            **kwargs,
        )

    monkeypatch.setattr(sequence_solver_module, "plan_strips", fail_once_then_plan)

    _production_run(
        spec,
        band_policy=policy,
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )

    assert plan_calls == [(6, policy), (spec.machine_count, policy)]


def test_sequence_band_policy_height_reserves_one_band_120_boundary_slot() -> None:
    portable = _production_run(
        band_120_control_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    ).heights
    fixed = _production_run(
        band_120_control_spec(),
        band_policy=BandPolicy("120"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    ).heights

    assert portable == (26, 33, 12, 16, 21, 28, 35, 14, 18, 23)
    assert fixed == (19, 33, 12, 16, 21, 28, 35, 14, 18, 23)
    assert len(fixed) == len(portable)


@pytest.mark.parametrize(
    ("selection", "height"),
    (("portable", 26), ("120", 19)),
)
def test_sequence_band_120_dropped_height_has_actual_clean_layout_control(
    selection: str,
    height: int,
) -> None:
    spec = band_120_control_spec()
    strips = plan_strips(spec, strip_len=6)
    direct_candidates = freeform_module._direct_net_candidates(strips, spec)
    seed = _greedy_pack(strips, height)
    pack = freeform_module._pack(
        strips,
        height=height,
        width_bound=max(8, 2 * seed.width),
        time_budget_s=1.0,
        direct_candidates=direct_candidates,
        workers=1,
        seed=seed,
    )
    assert pack is not None
    run = _production_run(
        spec,
        band_policy=BandPolicy(selection),
        time_budget_s=5.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    state = next(candidate for candidate in run.solver._heights if candidate.height == height)
    decoded = sequence_solver_module._exact_pack_decoded(
        pack,
        strips,
        state.problem,
        direct_candidates=direct_candidates,
    )

    detailed = run.solver.close_exact_decoded(
        height,
        decoded,
        reason="band-policy-height-control",
    )

    assert detailed.routing.status is DetailedRouteStatus.ROUTED
    assert detailed.placement is not None
    assert validate.certify(detailed.placement, spec, expect_power=False).ok
    assert finalize.finalize_placement(
        detailed.placement,
        BandPolicy(selection),
    ).frame is not None


def test_sequence_band_policy_height_remaps_protected_followup_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sequence_solver_module,
        "_candidate_heights",
        lambda _strips: [18],
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_minimum_pack_width",
        lambda _strips, _height: 20,
    )

    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("120"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )

    assert run.heights == (18, 19)
    assert run.solver._protected_followup_heights == (19,)


def test_sequence_band_policy_height_derives_topology_role_after_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected: list[int | None] = []
    monkeypatch.setattr(
        sequence_solver_module,
        "_topology_beam_height",
        lambda _seeds, coarse, **_kwargs: coarse[0],
    )

    def capture_topology_role(
        *,
        strip_count: int,
        height: int | None,
        machine_count: int,
        sprayed_lanes: int,
        power: bool,
    ) -> bool:
        del strip_count, machine_count, sprayed_lanes, power
        selected.append(height)
        return False

    monkeypatch.setattr(
        sequence_solver_module,
        "_uses_topology_beam",
        capture_topology_role,
    )

    run = _production_run(
        band_120_control_spec(),
        band_policy=BandPolicy("120"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )

    assert selected == [19]
    assert selected[0] in run.heights


def test_sequence_band_policy_height_derives_shared_pack_role_after_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected: list[int] = []
    monkeypatch.setattr(
        sequence_solver_module,
        "_uses_shared_pack_candidate",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_shared_pack_height_rank",
        lambda **_kwargs: 0,
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_needs_topology_beam",
        lambda **_kwargs: False,
    )

    def capture_shared_pack(
        _strips: list[freeform_module.Strip],
        *,
        height: int,
        **_kwargs: object,
    ) -> None:
        selected.append(height)
        return None

    monkeypatch.setattr(sequence_solver_module, "_pack", capture_shared_pack)

    run = _production_run(
        band_120_control_spec(),
        band_policy=BandPolicy("120"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )

    assert selected == [19]
    assert selected[0] in run.heights


def test_sequence_portable_schedule_is_unchanged() -> None:
    strips = plan_strips(two_stage_spec(), strip_len=6)
    seeds = {
        height: _greedy_pack(strips, height)
        for height in freeform_module._candidate_heights(strips)
    }
    coarse = tuple(sorted(seeds, key=lambda height: (seeds[height].width, height)))
    neighbors = tuple(height + 2 for height in coarse if height + 2 not in seeds)

    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )

    assert run.heights == coarse + neighbors


@pytest.mark.parametrize(
    ("core_width", "core_height"),
    ((595, 19), (19, 595)),
)
def test_sequence_extent_gate_stops_before_preparation_and_detailed_routing(
    core_width: int,
    core_height: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sequence_solver_module,
        "_candidate_heights",
        lambda _strips: [19, 595],
    )
    monkeypatch.setattr(
        freeform_module,
        "_power_plan",
        lambda *_args, **_kwargs: pytest.fail("infeasible extent reached power planning"),
    )
    monkeypatch.setattr(
        freeform_module,
        "_core_bounds",
        lambda _canvas: (0, 0, core_width - 1, core_height - 1),
    )
    monkeypatch.setattr(
        sequence_solver_module,
        "_route_detailed_candidate",
        lambda *_args, **_kwargs: pytest.fail("infeasible extent reached detailed routing"),
    )
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("120"),
        time_budget_s=2.0,
        power=True,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    state = next(height for height in run.solver._heights if height.height == core_height)
    decoded = replace(
        decode_state(
            state.problem,
            AnnealState.initial(state.problem.size, 7),
        ),
        width=core_width,
    )

    candidate = run.solver.adapters.prepare(state.height, decoded)
    detailed = run.solver.adapters.detailed_route(candidate, 1_000)

    assert candidate.prepared is None
    assert candidate.preparation_error == "band-extent"
    assert candidate.projection_failures
    assert detailed.routing.status is DetailedRouteStatus.INVALID
    assert detailed.placement is None

    assert detailed.projection_failures == candidate.projection_failures


def test_sequence_extent_gate_uses_realized_core_not_nominal_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sequence_solver_module,
        "_candidate_heights",
        lambda _strips: [19, 595],
    )
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("120"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    state = next(height for height in run.solver._heights if height.height == 595)
    decoded = replace(
        decode_state(
            state.problem,
            AnnealState.initial(state.problem.size, 7),
        ),
        width=19,
    )

    candidate = run.solver.adapters.prepare(state.height, decoded)

    assert candidate.prepared is not None
    assert candidate.preparation_error is None
    assert candidate.projection_failures == ()


def test_validation_budget_status_cannot_install_exact_incumbent() -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),
        )
    )
    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig.test(),
    )
    solver.adapters = replace(
        solver.adapters,
        validate=lambda _placement: ValidationVerdict(
            ok=False,
            failed_checks=(),
            placement=None,
            status=DetailedRouteStatus.BUDGET,
        ),
    )

    with pytest.raises(NoValidLayout, match="cancelled"):
        solver.search(max_stages=1)

    assert solver._incumbent is None
    assert solver._stage_stats
    assert solver._stage_stats[-1].detailed_status is DetailedRouteStatus.BUDGET


def test_production_certify_maps_projection_cancellation_to_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
    )
    observed_cancelled: list[Callable[[], bool]] = []
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: SimpleNamespace(errors=()),
    )

    def cancel_finalization(
        _placement: Placement,
        _policy: BandPolicy,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Never:
        assert cancelled is not None
        observed_cancelled.append(cancelled)
        raise finalize.ProjectionCancelled

    monkeypatch.setattr(finalize, "finalize_placement", cancel_finalization)

    verdict = run.solver.adapters.validate(_placement(area=20, belt_tiles=4))

    assert observed_cancelled
    assert not verdict.ok
    assert verdict.status is DetailedRouteStatus.BUDGET
    assert verdict.placement is None
    assert verdict.failed_checks == ()
    assert verdict.projection_failures == ()


def test_legacy_finalizer_crossing_deadline_returns_incomplete_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    deadline = time.monotonic() + 100.0
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
        absolute_deadline=deadline,
    )
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: SimpleNamespace(errors=()),
    )
    monkeypatch.setattr(
        finalize,
        "finalize_placement",
        lambda placement, _policy: placement,
    )
    clock = iter((deadline - 1.0, deadline - 1.0, deadline + 1.0))
    monkeypatch.setattr(
        sequence_solver_module.time,
        "monotonic",
        lambda: next(clock),
    )

    verdict = run.solver.adapters.validate(_placement(area=20, belt_tiles=4))

    assert not verdict.ok
    assert verdict.status is DetailedRouteStatus.BUDGET
    assert verdict.placement is None
    assert verdict.failed_checks == ()
    assert verdict.projection_failures == ()