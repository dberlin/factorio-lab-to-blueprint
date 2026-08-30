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
from flab2bp.layout.base import NoValidLayout, PlacedBuilding, Placement
from flab2bp.layout.compact_seed import (
    CompactSeedConfig,
    CompactSeedDiagnostics,
    CompactSeedResult,
    CompactSeedStatus,
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
    _pose_stage_boundary_update,
    _production_run,
    _ProductionCandidate,
    _selected_direct_targets,
    _selected_strips,
    _variant_search_inputs,
)
from flab2bp.layout.strip_variants import (
    generate_strip_families,
    partition_strip_family,
    variants_for_count,
)
from flab2bp.spec import BuildSpec, MachineGroup
from tests.layout.test_freeform import (
    proliferated_spec,
    ray_receiver_spec,
    two_stage_spec,
)

Prepared = tuple[int, DecodedPlacement]


class _ProductionRunCapture(TypedDict, total=False):
    compact_seed_attempt: int | None
    compact_seed_config: CompactSeedConfig | None


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


@pytest.mark.parametrize(
    "quality_failure",
    (DetailedRouteStatus.STRANDED, DetailedRouteStatus.BUDGET),
)
def test_quality_failure_exits_and_following_stage_restores_global_feedback(
    quality_failure: DetailedRouteStatus,
) -> None:
    exact = _placement(area=20, belt_tiles=4)
    fake = _FakeRouting(
        detailed_results=(
            DetailedStageResult(_routing(DetailedRouteStatus.ROUTED), exact),
            DetailedStageResult(
                _routing(quality_failure, geometric_failure=True),
                None,
            ),
            DetailedStageResult(
                _routing(DetailedRouteStatus.STRANDED, geometric_failure=True),
                None,
            ),
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
    assert failure.global_routes == 0
    assert failure.global_skip_reason == "quality-mode"
    assert failure.objective_mode is sequence_solver_module.ObjectiveMode.EXPLORATION
    assert failure.quality_exited
    assert not solver._heights[0].feedback.cell_history
    assert len(fake.global_allowances) == 1

    final_result = solver.search(max_stages=3)

    restored = final_result.stages[2]
    assert restored.global_routes == 1
    assert restored.global_skip_reason is None
    assert restored.objective_mode is sequence_solver_module.ObjectiveMode.EXPLORATION
    assert solver._heights[0].feedback.cell_history == {(0, 0, 0): 1.0}
    assert len(fake.global_allowances) == 2


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
            power,
            strip_len,
            config,
            belt_vertical_construction,
            absolute_deadline,
            compact_seed_base_seed,
        )
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
        (95, 27, 6, 27, 0, 1),
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


def test_tall_topology_height_uses_highest_bound_rank_not_numeric_height() -> None:
    assert (
        sequence_solver_module._topology_beam_height(
            {},
            (89, 70, 56, 44, 33),
            machine_count=57,
            strip_count=14,
            sprayed_lanes=14,
            power=False,
        )
        == 33
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
    target = DirectInsertTarget((0, 1), 0, 1, 2, 4, 10, 4)
    strips = (
        type("StripOffset", (), {"west_channel": 3})(),
        type("StripOffset", (), {"west_channel": 1})(),
    )

    assert sequence_solver_module._refinement_direct_targets((target,), strips) == (
        replace(target, producer_span=12, consumer_span=2),
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


def test_validator_started_before_deadline_may_finish_exact_certification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Report:
        errors: tuple[()] = ()

    def slow_certify(
        _placement: Placement,
        _spec: BuildSpec,
        *,
        expect_power: bool,
    ) -> Report:
        del expect_power
        time.sleep(0.1)
        return Report()

    monkeypatch.setattr(validate, "certify", slow_certify)
    run = _production_run(
        two_stage_spec(),
        band_policy=BandPolicy("portable"),
        time_budget_s=2.0,
        power=False,
        strip_len=6,
        config=SequenceSolverConfig.test(),
        absolute_deadline=time.monotonic() + 0.05,
    )

    candidate = _placement(area=1, belt_tiles=1)
    verdict = run.solver.adapters.validate(candidate)

    assert verdict.ok
    assert verdict.failed_checks == ()
    assert verdict.placement is not None


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


def test_compact_direct_eligibility_contains_exactly_authoritative_variant_targets() -> None:
    spec, strips, problem = _two_stage_variant_problem()
    enumerate_eligibility = getattr(
        sequence_solver_module,
        "_variant_direct_eligibility",
        None,
    )
    assert enumerate_eligibility is not None

    actual = enumerate_eligibility(spec, strips, problem)
    expected: set[VariantDirectInsertTarget] = set()
    for baseline in _selected_direct_targets(
        spec,
        strips,
        problem,
        (0,) * problem.size,
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
        _result: DetailedRouteResult,
        _stagnation: int,
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
        _result: DetailedRouteResult,
        _stagnation: int,
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
        result: DetailedRouteResult,
        stagnation: int,
    ) -> StageBoundaryUpdate | None:
        update = _pose_stage_boundary_update(
            stage_problem,
            stage_state,
            result,
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
    solver = _solver(
        fake,
        heights=(40,),
        config=SequenceSolverConfig(
            stages=1,
            moves_per_stage=1,
            restarts_per_height=1,
            global_elites=1,
        ),
    )
    solver.adapters = replace(
        solver.adapters,
        validate=production.solver.adapters.validate,
    )
    serial_run = replace(
        production,
        solver=solver,
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
    assert placement is finalized[0]


@pytest.mark.parametrize("power", [False, True])
@pytest.mark.parametrize("belt_vertical_construction", [False, True])
def test_sequence_backend_returns_only_certified_placements(
    power: bool,
    belt_vertical_construction: bool,
) -> None:
    spec = two_stage_spec()
    placement = SequencePairLayout(
        band_policy=BandPolicy("portable"),
        power=power,
        belt_vertical_construction=belt_vertical_construction,
        config=SequenceSolverConfig.test(),
    ).lay_out(spec, time_budget_s=2.0)

    assert not validate.validate(
        placement,
        spec,
        ids=validate.id_map(spec),
        expect_power=power,
        belt_vertical_construction=belt_vertical_construction,
    ).errors
    backend: object = placement.stats["backend"]
    assert backend == "sequence-pair"
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

    assert all(result.placement.stats[key] == value for key, value in original_stats.items())
    assert result.placement is placement is python_placement is mixed_placement
    assert result.exact_candidate_key == exact_stage.candidate_key


def test_sequence_reuses_adaptive_coarse_strip_partition_before_problem_identity() -> None:
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
    fine = plan_strips(spec, strip_len=6)
    assert len(fine) == 40

    run = _production_run(
        spec,
        band_policy=BandPolicy("portable"),
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
    selected = _selected_strips(strips, problem, (0,) * problem.size)
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
    assert prepared.junction_ban
    assert any(level > 0 for _x, _y, level in prepared.junction_ban)
    assert workspace.canvas.junction_geometry_prepared
    assert workspace.canvas.junction_ban == set(prepared.junction_ban)
    assert prepared.junction_ban == freeform_module._prepared_junction_ban(
        prepared.building_templates,
        prepared.power_sites,
    )


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
    assert not validate.certify(placement, spec, expect_power=False).errors


@pytest.mark.slow
def test_sequence_pair_routes_self_consuming_pinned_flow(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    placement = SequencePairLayout(
        band_policy=BandPolicy("portable"),
        power=False, islands=1
    ).lay_out(
        refined_oil_feedback_spec,
        time_budget_s=15.0,
    )
    assert validate.certify(
        placement,
        refined_oil_feedback_spec,
        expect_power=False,
    ).ok
