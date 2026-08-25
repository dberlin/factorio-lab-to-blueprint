"""Deterministic staged orchestration for sequence-pair routing search.

The generic scheduler keeps proxy placement, relaxed routing, detailed
emission, and exact acceptance separate.  The public layout binds those stages
to the current freeform geometry, routers, power planner, and validator.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Any, Protocol, cast

from flab2bp.layout import validate
from flab2bp.layout.base import RETRY_BUDGET_S, NoValidLayout, Placement
from flab2bp.layout.freeform import (
    _ROUTING_BUDGET,
    _ROUTING_EXPANSIONS_PER_SECOND,
    WEST_CHANNEL,
    Strip,
    _box,
    _build_prepared,
    _candidate_heights,
    _direct_alignment_targets,
    _direct_net_candidates,
    _fanout_shortfall,
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
    RouteFailureKind,
    decay_feedback,
    feedback_cost_context,
    remap_feedback_nets,
    select_lns_neighbourhood,
    select_split_candidate,
    update_feedback,
)
from flab2bp.layout.sequence_pair import (
    AnnealConfig,
    AnnealState,
    DecodedPlacement,
    DirectInsertTarget,
    PlacementProblem,
    StageBoundaryUpdate,
    align_direct_inserts,
    anneal_stage,
    derive_stage_seed,
    repair_neighbourhood,
    split_stage_boundary,
)
from flab2bp.layout.strip_variants import (
    StripInstanceId,
    StripVariant,
    StripVariantId,
    default_strip_variant,
    generate_strip_families,
    partition_strip_family,
    variants_for_count,
)
from flab2bp.spec import BuildSpec


@dataclass(frozen=True, slots=True)
class SequenceSolverConfig:
    """Fixed deterministic orchestration constants."""

    stages: int = 6
    moves_per_stage: int = 2_000
    restarts_per_height: int = 2
    global_elites: int = 3
    global_rounds: int = 5
    final_reserve_fraction: Fraction = Fraction(1, 4)
    seed: int = 20260824

    def __post_init__(self) -> None:
        for value, name in (
            (self.stages, "stages"),
            (self.moves_per_stage, "moves per stage"),
            (self.restarts_per_height, "restarts per height"),
            (self.global_elites, "global elites"),
            (self.global_rounds, "global rounds"),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.final_reserve_fraction, Fraction) or not (
            0 <= self.final_reserve_fraction < 1
        ):
            raise ValueError("final reserve fraction must be a Fraction from zero to one")
        if type(self.seed) is not int:
            raise ValueError("solver seed must be an integer")

    @classmethod
    def test(cls) -> SequenceSolverConfig:
        """Return a small deterministic configuration for focused tests."""
        return cls(stages=2, moves_per_stage=16, restarts_per_height=1, global_elites=2)


@dataclass(slots=True)
class ExpansionBudget:
    """One deterministic expansion ledger with a stage-inaccessible reserve."""

    total: int
    discovery_by_height: dict[int, int] = field(default_factory=dict, init=False)
    shared_left: int = field(init=False)
    final_reserved: int = field(init=False)
    _spent: int = field(default=0, init=False, repr=False)
    _unsettled_discovery: set[int] = field(default_factory=set, init=False, repr=False)
    _pending_discovery_return: int = field(default=0, init=False, repr=False)
    _configured: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.total) is not int or self.total < 0:
            raise ValueError("total expansion budget must be a non-negative integer")
        self.final_reserved = _fraction_ceiling(self.total, Fraction(1, 4))
        self.shared_left = self.total - self.final_reserved

    @property
    def spent(self) -> int:
        """Expansions actually charged to discovery and shared stage routing."""
        return self._spent

    @property
    def searchable_total(self) -> int:
        """Budget visible to stage routing; the final reserve is excluded."""
        return self.total - self.final_reserved

    @property
    def discovery_complete(self) -> bool:
        return self._configured and not self._unsettled_discovery

    def configure(self, heights: tuple[int, ...], reserve_fraction: Fraction) -> None:
        """Partition searchable expansions equally across first height stages."""
        if self._configured:
            if tuple(self.discovery_by_height) != heights:
                raise ValueError("expansion budget is already configured for other heights")
            return
        if not heights or len(set(heights)) != len(heights):
            raise ValueError("candidate heights must be a non-empty tuple of unique values")
        if not isinstance(reserve_fraction, Fraction) or not 0 <= reserve_fraction < 1:
            raise ValueError("reserve fraction must be a Fraction from zero to one")

        self.final_reserved = _fraction_ceiling(self.total, reserve_fraction)
        searchable = self.total - self.final_reserved
        discovery_slice, remainder = divmod(searchable, len(heights))
        self.discovery_by_height = {height: discovery_slice for height in heights}
        self.shared_left = remainder
        self._unsettled_discovery = set(heights)
        self._configured = True

    def discovery_allowance(self, height: int) -> int:
        if height not in self._unsettled_discovery:
            raise ValueError("height has no unsettled discovery reservation")
        return self.discovery_by_height[height]

    def settle_discovery(self, height: int, spent: int) -> None:
        allowance = self.discovery_allowance(height)
        _check_spend(spent, allowance)
        self._spent += spent
        self._pending_discovery_return += allowance - spent
        self._unsettled_discovery.remove(height)
        if not self._unsettled_discovery:
            self.shared_left += self._pending_discovery_return
            self._pending_discovery_return = 0

    def shared_allowance(self) -> int:
        if not self.discovery_complete:
            raise ValueError("shared expansion budget is locked until discovery completes")
        return self.shared_left

    def settle_shared(self, spent: int) -> None:
        allowance = self.shared_allowance()
        _check_spend(spent, allowance)
        self.shared_left -= spent
        self._spent += spent


def _fraction_ceiling(total: int, fraction: Fraction) -> int:
    numerator = total * fraction.numerator
    return (numerator + fraction.denominator - 1) // fraction.denominator


def _check_spend(spent: int, allowance: int) -> None:
    if type(spent) is not int or not 0 <= spent <= allowance:
        raise ValueError("adapter expansion spend must be within its allowance")


@dataclass(frozen=True, slots=True)
class DetailedStageResult:
    """Detailed diagnostic and the complete placement it may have emitted."""

    routing: DetailedRouteResult
    placement: Placement | None


@dataclass(frozen=True, slots=True)
class ValidationVerdict:
    """Stable exact-validator outcome returned by an injected adapter."""

    ok: bool
    failed_checks: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.ok) is not bool:
            raise ValueError("validation verdict ok flag must be a bool")
        if not isinstance(self.failed_checks, tuple) or any(
            not isinstance(check, str) or not check for check in self.failed_checks
        ):
            raise ValueError("validation failure checks must be non-empty strings in a tuple")
        if self.ok and self.failed_checks:
            raise ValueError("a clean validation verdict cannot contain failed checks")


@dataclass(frozen=True, slots=True)
class StageAdapters[PreparedT]:
    """Production-independent routing and exact-validation boundary."""

    prepare: Callable[[int, DecodedPlacement], PreparedT]
    global_route: Callable[[PreparedT, FeedbackState, int], GlobalRouteResult]
    detailed_route: Callable[[PreparedT, int], DetailedStageResult]
    validate: Callable[[Placement], ValidationVerdict]


@dataclass(frozen=True, slots=True)
class StageStats:
    """Deterministic observations from one closed temperature stage."""

    height: int
    restart: int
    stage_index: int
    seed: int
    accepted_moves: int
    global_routes: int
    global_overflow: int
    detailed_status: DetailedRouteStatus
    stranded: int
    expansions: int
    lns_size: int
    exact_key: tuple[int, int] | None
    validation_failures: tuple[str, ...]
    variant_moves: int
    selected_instance_ids: tuple[StripInstanceId, ...]
    selected_variant_ids: tuple[StripVariantId, ...]
    selected_pose_yaws: tuple[float, ...]
    split_count: int
    merge_count: int


@dataclass(frozen=True, slots=True)
class SequenceSearchResult:
    """Only an exact, detailed-routed, validator-clean incumbent."""

    placement: Placement
    exact_key: tuple[int, int]
    stages: tuple[StageStats, ...]
    termination: str


@dataclass(slots=True)
class _RestartState:
    restart: int
    seed: int
    anneal: AnnealState
    failure_signature: tuple[object, ...] = ()
    feedback_stagnation: int = 0
    stages: int = 0


@dataclass(slots=True)
class _HeightState:
    order: int
    height: int
    problem: PlacementProblem
    feedback: FeedbackState
    restarts: list[_RestartState]
    stages: int = 0
    spent: int = 0
    stranded: int = 1 << 60
    global_overflow: int = 1 << 60
    estimated_area: int = 1 << 60
    exact_key: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class _GlobalCandidate[PreparedT]:
    prepared: PreparedT
    state: AnnealState
    decoded: DecodedPlacement
    result: GlobalRouteResult


StageBoundaryTransform = Callable[
    [
        int,
        PlacementProblem,
        AnnealState,
        FeedbackState,
        DetailedRouteResult,
        int,
    ],
    StageBoundaryUpdate | None,
]


class SequenceSolver[PreparedT]:
    """Run deterministic discovery, then best-first closed routing stages."""

    def __init__(
        self,
        *,
        heights: tuple[int, ...],
        problem_for_height: Callable[[int], PlacementProblem],
        adapters: StageAdapters[PreparedT],
        expansion_budget: ExpansionBudget,
        config: SequenceSolverConfig | None = None,
        deadline_reached: Callable[[], bool] | None = None,
        initial_feedback: Callable[[PlacementProblem], FeedbackState] | None = None,
        direct_targets: tuple[DirectInsertTarget, ...] = (),
        direct_targets_for_state: Callable[
            [PlacementProblem, AnnealState], tuple[DirectInsertTarget, ...]
        ]
        | None = None,
        stage_boundary_transform: StageBoundaryTransform | None = None,
    ) -> None:
        if (
            not isinstance(heights, tuple)
            or not heights
            or len(set(heights)) != len(heights)
            or any(type(height) is not int or height <= 0 for height in heights)
        ):
            raise ValueError("candidate heights must be unique positive integers in a tuple")
        self.config = config or SequenceSolverConfig()
        self.adapters = adapters
        self.budget = expansion_budget
        self.deadline_reached = deadline_reached or (lambda: False)
        if not isinstance(direct_targets, tuple):
            raise ValueError("direct-insert targets must be an immutable tuple")
        self.direct_targets = direct_targets
        self.stage_boundary_transform = stage_boundary_transform
        self.direct_targets_for_state = direct_targets_for_state
        self.budget.configure(heights, self.config.final_reserve_fraction)
        feedback_factory = initial_feedback or _default_feedback
        self._heights = [
            _new_height_state(
                order,
                height,
                problem_for_height(height),
                feedback_factory,
                self.config,
            )
            for order, height in enumerate(heights)
        ]
        self._stage_stats: list[StageStats] = []
        self._incumbent: tuple[tuple[int, int], Placement] | None = None

    def search(self, *, max_stages: int | None = None) -> SequenceSearchResult:
        """Search until its stage cap, deadline, or searchable budget is exhausted."""
        stage_limit = (
            self.config.stages * self.config.restarts_per_height * len(self._heights)
            if max_stages is None
            else max_stages
        )
        if type(stage_limit) is not int or stage_limit < 0:
            raise ValueError("maximum stages must be a non-negative integer")

        termination = "stage-limit"
        while len(self._stage_stats) < stage_limit:
            if self.deadline_reached():
                termination = "deadline"
                break

            discovery = next((height for height in self._heights if height.stages == 0), None)
            if discovery is not None:
                height_state = discovery
                allowance = self.budget.discovery_allowance(height_state.height)
            else:
                if self.budget.shared_left == 0:
                    termination = "budget"
                    break
                eligible = [
                    height
                    for height in self._heights
                    if any(run.stages < self.config.stages for run in height.restarts)
                ]
                if not eligible:
                    termination = "candidates"
                    break
                height_state = min(eligible, key=_height_priority)
                allowance = self.budget.shared_allowance()

            restart = min(
                (run for run in height_state.restarts if run.stages < self.config.stages),
                key=lambda run: (run.stages, run.restart),
            )
            spent, cancelled = self._run_stage(height_state, restart, allowance)
            if discovery is not None:
                self.budget.settle_discovery(height_state.height, spent)
            else:
                self.budget.settle_shared(spent)
            if cancelled:
                termination = "cancelled"
                break

        if self._incumbent is None:
            reason = {
                "deadline": "deadline exhausted before finding an exact layout",
                "budget": "expansion budget exhausted before finding an exact layout",
                "candidates": "all scheduled candidates were exhausted",
                "cancelled": "routing was cancelled before detailed emission",
                "stage-limit": "no scheduled stage produced an exact layout",
            }[termination]
            raise NoValidLayout(reason)
        exact_key, placement = self._incumbent
        return SequenceSearchResult(
            placement=placement,
            exact_key=exact_key,
            stages=tuple(self._stage_stats),
            termination=termination,
        )

    def _run_stage(
        self,
        height_state: _HeightState,
        restart: _RestartState,
        allowance: int,
    ) -> tuple[int, bool]:
        stage_start = restart.anneal
        problem = height_state.problem
        context = feedback_cost_context(
            height_state.feedback,
            problem,
            self.direct_targets,
        )
        stage_config = AnnealConfig(
            moves_per_stage=self.config.moves_per_stage,
            elite_count=max(self.config.global_elites, 1),
        )
        if self.direct_targets_for_state is None:
            annealed = anneal_stage(
                problem,
                restart.anneal,
                stage_config,
                context,
            )
        else:
            annealed = anneal_stage(
                problem,
                restart.anneal,
                stage_config,
                context,
                direct_targets_for_state=self.direct_targets_for_state,
            )

        spent = 0
        global_candidates: list[_GlobalCandidate[PreparedT]] = []
        for elite in annealed.elites[: self.config.global_elites]:
            prepared = self.adapters.prepare(height_state.height, elite.decoded)
            remaining = allowance - spent
            global_result = self.adapters.global_route(
                prepared,
                height_state.feedback,
                remaining,
            )
            _check_spend(global_result.expansions, remaining)
            spent += global_result.expansions
            global_candidates.append(
                _GlobalCandidate(
                    prepared=prepared,
                    state=elite.state,
                    decoded=elite.decoded,
                    result=global_result,
                )
            )

        selected = min(global_candidates, key=_global_priority)
        if selected.result.cancelled:
            return spent, True
        detailed = self.adapters.detailed_route(selected.prepared, allowance - spent)
        _check_spend(detailed.routing.expansions, allowance - spent)
        spent += detailed.routing.expansions

        exact_key: tuple[int, int] | None = None
        validation_failures: tuple[str, ...] = ()
        if detailed.routing.status is DetailedRouteStatus.ROUTED and detailed.placement is not None:
            verdict = self.adapters.validate(detailed.placement)
            validation_failures = verdict.failed_checks
            if verdict.ok:
                exact_key = _exact_key(detailed.placement)
                if self._incumbent is None or exact_key < self._incumbent[0]:
                    self._incumbent = exact_key, detailed.placement
                if height_state.exact_key is None or exact_key < height_state.exact_key:
                    height_state.exact_key = exact_key

        height_state.feedback = update_feedback(
            decay_feedback(height_state.feedback), detailed.routing
        )
        signature = tuple(
            (
                failure.net_id.logical,
                failure.kind,
                tuple(net.logical for net in failure.blocking_nets),
            )
            for failure in detailed.routing.failures
            if failure.kind
            not in {
                RouteFailureKind.STATIC_ACCESS,
                RouteFailureKind.BUDGET,
            }
        )
        if signature:
            restart.feedback_stagnation = (
                restart.feedback_stagnation + 1 if signature == restart.failure_signature else 1
            )
        else:
            restart.feedback_stagnation = 0
        restart.failure_signature = signature
        neighbourhood = frozenset[int]()
        next_anneal = AnnealState(
            pair=selected.state.pair,
            gaps=selected.state.gaps,
            base_seed=restart.seed,
            stage_index=annealed.final_state.stage_index,
            variant_indices=selected.state.variant_indices,
        )
        if 0 < detailed.routing.failed_count <= 3:
            neighbourhood = _lns_neighbourhood(
                detailed.routing, selected.state, problem, selected.decoded
            )
            if neighbourhood:
                repaired = repair_neighbourhood(
                    selected.state.pair,
                    selected.state.gaps,
                    neighbourhood,
                    seed=derive_stage_seed(restart.seed, annealed.final_state.stage_index),
                    variant_indices=selected.state.variant_indices,
                )
                next_anneal = AnnealState(
                    pair=repaired.pair,
                    gaps=repaired.gaps,
                    base_seed=restart.seed,
                    stage_index=annealed.final_state.stage_index,
                    variant_indices=repaired.variant_indices,
                )
        split_count = 0
        merge_count = 0
        if self.stage_boundary_transform is not None and signature:
            transformed = self.stage_boundary_transform(
                height_state.height,
                problem,
                next_anneal,
                height_state.feedback,
                detailed.routing,
                restart.feedback_stagnation,
            )
            if transformed is not None:
                for other in height_state.restarts:
                    if other is restart:
                        continue
                    sibling = self.stage_boundary_transform(
                        height_state.height,
                        problem,
                        other.anneal,
                        height_state.feedback,
                        detailed.routing,
                        restart.feedback_stagnation,
                    )
                    if sibling is None or sibling.problem != transformed.problem:
                        raise ValueError(
                            "stage-boundary transform must rebuild every restart identically"
                        )
                    other.anneal = sibling.state
                    other.failure_signature = ()
                    other.feedback_stagnation = 0
                height_state.problem = transformed.problem
                next_anneal = transformed.state
                cardinality_delta = transformed.problem.size - problem.size
                split_count = max(0, cardinality_delta)
                merge_count = max(0, -cardinality_delta)
                height_state.feedback = remap_feedback_nets(
                    height_state.feedback,
                    (),
                )
                restart.failure_signature = ()
                restart.feedback_stagnation = 0

        restart.anneal = next_anneal
        restart.stages += 1
        height_state.stages += 1
        height_state.spent += spent
        height_state.stranded = detailed.routing.failed_count
        height_state.global_overflow = selected.result.total_overflow
        height_state.estimated_area = selected.decoded.width * height_state.height
        selected_variant_ids = problem.selected_variant_ids(selected.state.variant_indices)
        selected_pose_yaws = (
            tuple(
                problem.variant(strip, variant).yaw
                for strip, variant in enumerate(selected.state.variant_indices)
            )
            if problem.variant_tables
            else ()
        )
        stage_start_variants = stage_start.variant_indices or (0,) * problem.size
        selected_variants = selected.state.variant_indices or (0,) * problem.size
        variant_moves = sum(
            before != after
            for before, after in zip(
                stage_start_variants,
                selected_variants,
                strict=True,
            )
        )
        self._stage_stats.append(
            StageStats(
                height=height_state.height,
                restart=restart.restart,
                stage_index=restart.stages - 1,
                seed=restart.seed,
                accepted_moves=annealed.accepted_moves,
                global_routes=len(global_candidates),
                global_overflow=selected.result.total_overflow,
                detailed_status=detailed.routing.status,
                stranded=detailed.routing.failed_count,
                expansions=spent,
                lns_size=len(neighbourhood),
                exact_key=exact_key,
                validation_failures=validation_failures,
                variant_moves=variant_moves,
                selected_instance_ids=problem.instance_ids,
                selected_variant_ids=selected_variant_ids,
                selected_pose_yaws=selected_pose_yaws,
                split_count=split_count,
                merge_count=merge_count,
            )
        )
        return spent, False


def _lns_neighbourhood(
    detailed: DetailedRouteResult,
    selected_state: AnnealState,
    problem: PlacementProblem,
    decoded: DecodedPlacement,
) -> frozenset[int]:
    return select_lns_neighbourhood(
        detailed,
        selected_state.pair,
        selected_state.gaps,
        problem,
        decoded,
    )


def _default_feedback(problem: PlacementProblem) -> FeedbackState:
    widths = (
        tuple(max(variant.box_width for variant in table) for table in problem.variant_tables)
        if problem.variant_tables
        else tuple(width for width, _height in problem.sizes)
    )
    return FeedbackState.empty((sum(widths) + 4 * problem.size, problem.outline_height))


def _new_height_state(
    order: int,
    height: int,
    problem: PlacementProblem,
    feedback_factory: Callable[[PlacementProblem], FeedbackState],
    config: SequenceSolverConfig,
) -> _HeightState:
    if problem.outline_height != height:
        raise ValueError("height problem outline must match its scheduled height")
    height_seed = derive_stage_seed(config.seed, order)
    restarts = [
        _RestartState(
            restart=restart,
            seed=(seed := derive_stage_seed(height_seed, restart)),
            anneal=AnnealState.initial(problem.size, seed),
        )
        for restart in range(config.restarts_per_height)
    ]
    return _HeightState(
        order=order,
        height=height,
        problem=problem,
        feedback=feedback_factory(problem),
        restarts=restarts,
    )


def _height_priority(height: _HeightState) -> tuple[int, int, int, int, int, int]:
    area = height.exact_key[0] if height.exact_key is not None else height.estimated_area
    return (
        0 if height.exact_key is not None else 1,
        height.stranded,
        height.global_overflow,
        area,
        height.spent,
        height.order,
    )


def _global_priority(
    candidate: _GlobalCandidate[Any],
) -> tuple[int, int, int, int, int, int, int, tuple[int, ...], tuple[int, ...]]:
    result = candidate.result
    return (
        int(result.cancelled),
        int(result.exhausted_budget),
        result.unreachable_ports,
        result.total_overflow,
        candidate.decoded.width * candidate.decoded.used_height,
        sum(net.length + net.level_changes for net in result.net_results),
        candidate.decoded.gap_area,
        candidate.decoded.x,
        candidate.decoded.y,
    )


def _exact_key(placement: Placement) -> tuple[int, int]:
    belt_tiles = placement.stats.get("belt_tiles")
    if (
        not isinstance(belt_tiles, (int, float))
        or isinstance(belt_tiles, bool)
        or belt_tiles < 0
        or int(belt_tiles) != belt_tiles
    ):
        raise ValueError("validated placement must report an integral belt_tiles stat")
    return placement.area, int(belt_tiles)


def _variant_search_inputs(
    spec: BuildSpec,
    strips: list[Strip],
    *,
    strip_len: int,
) -> tuple[
    tuple[StripInstanceId, ...],
    tuple[tuple[StripVariant, ...], ...],
]:
    """Match legacy strip order to exact instance identities and variant tables."""
    instance_ids: list[StripInstanceId] = []
    variant_tables: list[tuple[StripVariant, ...]] = []
    strip_index = 0
    for family in generate_strip_families(spec):
        if not family.variants:
            return (), ()
        default = default_strip_variant(family)
        instances = partition_strip_family(
            family,
            max_machine_count=max(1, strip_len),
            variant_id=default.variant_id,
        )
        for instance in instances:
            if strip_index >= len(strips):
                raise ValueError("physical strip plan ended before its variant instances")
            strip = strips[strip_index]
            if (
                strip.group_key != family.group_key
                or strip.recipe_id != family.recipe_id
                or strip.machines != instance.machine_count
            ):
                raise ValueError("physical strip plan and variant instance order disagree")
            realized = variants_for_count(family, instance.machine_count)
            variants = (instance.variant,) + tuple(
                variant for variant in realized if variant.variant_id != instance.variant.variant_id
            )
            instance_ids.append(instance.instance_id)
            variant_tables.append(variants)
            strip_index += 1
    if strip_index != len(strips):
        raise ValueError("physical strip plan contains unmatched compatibility strips")
    return tuple(instance_ids), tuple(variant_tables)


def _selected_strips(
    strips: list[Strip],
    problem: PlacementProblem,
    variant_indices: tuple[int, ...],
) -> list[Strip]:
    """Project current instance ranges into exact Freeform physical plans."""
    problem.selected_sizes(variant_indices)
    if not problem.variant_tables:
        return list(strips)
    exact_templates = {
        (strip.family_id, strip.machine_start, strip.machines): strip
        for strip in strips
        if strip.family_id is not None
    }
    family_templates = {strip.family_id: strip for strip in strips if strip.family_id is not None}
    selected: list[Strip] = []
    for index, instance_id in enumerate(problem.instance_ids):
        strip = exact_templates.get(
            (
                instance_id.family_id,
                instance_id.machine_start,
                instance_id.machine_count,
            )
        ) or family_templates.get(instance_id.family_id)
        if strip is None:
            if len(strips) != problem.size:
                raise ValueError("physical strip templates do not cover the placement instances")
            strip = strips[index]
        variant = problem.variant(index, variant_indices[index])
        selected.append(
            replace(
                strip,
                machines=instance_id.machine_count,
                mw=variant.footprint_width,
                mh=variant.footprint_height,
                yaw=variant.yaw,
                pw=variant.pitch_x,
                ph=variant.pitch_y,
                lane_plan=variant.lane_plan,
                attachment_plan=variant.attachment_plan,
                box_height=variant.box_height,
                family_id=instance_id.family_id,
                machine_start=instance_id.machine_start,
            )
        )
    return selected


def _selected_direct_targets(
    spec: BuildSpec,
    strips: list[Strip],
    problem: PlacementProblem,
    variant_indices: tuple[int, ...],
) -> tuple[DirectInsertTarget, ...]:
    """Derive pair geometry only after both complete endpoint variants are selected."""
    selected = _selected_strips(strips, problem, variant_indices)
    return _direct_alignment_targets(_direct_net_candidates(selected, spec))


def _rebuild_stage_problem_nets(
    problem: PlacementProblem,
    nets: tuple[tuple[int, int], ...],
) -> PlacementProblem:
    """Rebind sorted physical nets and their logical families as one value."""
    logical_net_families = (
        tuple(
            (
                problem.instance_ids[source].family_id,
                problem.instance_ids[destination].family_id,
            )
            for source, destination in nets
        )
        if problem.instance_ids
        else ()
    )
    return replace(
        problem,
        nets=nets,
        logical_net_families=logical_net_families,
    )


@dataclass(frozen=True, slots=True)
class _ProductionCandidate:
    height: int
    problem: PlacementProblem
    decoded: DecodedPlacement
    pack: _Pack
    prepared: _PreparedRoutingProblem | None
    preparation_error: str | None = None
    selected_strips: tuple[Strip, ...] = ()


@dataclass(slots=True)
class _ProductionTelemetry:
    planning_time_s: float = 0.0
    preparation_time_s: float = 0.0
    global_route_time_s: float = 0.0
    detailed_route_time_s: float = 0.0
    validation_time_s: float = 0.0
    global_routes: int = 0
    detailed_routes: int = 0
    global_expansions: int = 0
    detailed_expansions: int = 0
    best_overflow: int | None = None
    best_stranded: int | None = None
    feedback_nets: int = 0
    feedback_cells: int = 0
    pose_feasibility_rejects: int = 0
    elevated_coater_routes: int = 0


@dataclass(frozen=True, slots=True)
class _ProductionRun:
    solver: SequenceSolver[_ProductionCandidate]
    telemetry: _ProductionTelemetry
    heights: tuple[int, ...]
    direct_candidates: int
    started: float
    ceiling: float


def _empty_global_result(*, exhausted: bool, cancelled: bool = False) -> GlobalRouteResult:
    return GlobalRouteResult(
        net_results=(),
        paths={},
        overflow_cells=0,
        total_overflow=0,
        max_overflow=0,
        unreachable_ports=1,
        rounds=0,
        expansions=0,
        exhausted_budget=exhausted,
        hot_cells=(),
        hot_regions=(),
        cancelled=cancelled,
    )


def _closed_detailed_result(
    status: DetailedRouteStatus, *, expansions: int = 0
) -> DetailedStageResult:
    return DetailedStageResult(
        routing=DetailedRouteResult(
            status=status,
            routed=(),
            failures=(),
            iterations=0,
            expansions=expansions,
        ),
        placement=None,
    )


def _route_detailed_candidate(
    spec: BuildSpec,
    strips: list[Strip],
    prepared: _PreparedRoutingProblem,
    *,
    power: bool,
    deadline: float | None,
    allowance: int,
) -> DetailedStageResult:
    """Route one exact prepared identity and withhold every partial build."""
    attempt_budget = {"left": allowance}
    try:
        built = _build_prepared(
            spec,
            strips,
            prepared,
            power=power,
            route=True,
            deadline=deadline,
            budget=attempt_budget,
        )
    except _Unpowerable:
        expansions = allowance - attempt_budget["left"]
        _check_spend(expansions, allowance)
        return _closed_detailed_result(
            DetailedRouteStatus.UNPOWERABLE,
            expansions=expansions,
        )
    return DetailedStageResult(
        routing=built.routing,
        placement=(built.placement if built.routing.status is DetailedRouteStatus.ROUTED else None),
    )


def _production_run(
    spec: BuildSpec,
    *,
    time_budget_s: float,
    power: bool,
    strip_len: int,
    config: SequenceSolverConfig,
) -> _ProductionRun:
    started = time.monotonic()
    ceiling = max(time_budget_s, RETRY_BUDGET_S)
    deadline = started + ceiling

    def deadline_reached() -> bool:
        return time.monotonic() >= deadline

    telemetry = _ProductionTelemetry()

    planning_started = time.monotonic()
    try:
        planned_strip_len = strip_len
        try:
            strips = plan_strips(spec, strip_len=planned_strip_len)
        except (KeyError, ValueError) as exc:
            try:
                planned_strip_len = max(1, spec.machine_count)
                strips = plan_strips(spec, strip_len=planned_strip_len)
            except (KeyError, ValueError):
                raise NoValidLayout(
                    f"the spec cannot be split into strips: {exc}",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                ) from exc
        if not strips:
            raise NoValidLayout(
                "the spec contains no machine groups",
                spec_label=spec.label,
                budget_s=time_budget_s,
            )
        shortfall = _fanout_shortfall(strips)
        if shortfall:
            raise NoValidLayout(
                "a producer lane has fewer tiles than the consumers it must tap, "
                "so two junctions would have to share one tile. " + "; ".join(shortfall[:3]),
                spec_label=spec.label,
                budget_s=0.0,
            )

        instance_ids, variant_tables = _variant_search_inputs(
            spec,
            strips,
            strip_len=planned_strip_len,
        )
        direct_candidates = _direct_net_candidates(strips, spec)
        direct_targets = _direct_alignment_targets(direct_candidates)
        sizes = tuple(_box(strip) for strip in strips)
        nets = tuple(_nets_between(strips))
        area_lower_bound = (
            sum(
                min(
                    (variant.box_width + sizes[strip][0] - variants[0].box_width)
                    * (variant.box_height + sizes[strip][1] - variants[0].box_height)
                    for variant in variants
                )
                for strip, variants in enumerate(variant_tables)
            )
            if variant_tables
            else sum(width * height for width, height in sizes)
        )
        seeds = {height: _greedy_pack(strips, height) for height in _candidate_heights(strips)}
        heights = tuple(sorted(seeds, key=lambda height: (seeds[height].width, height)))
        problems = {
            height: PlacementProblem(
                sizes=sizes,
                nets=nets,
                outline_height=height,
                area_lower_bound=area_lower_bound,
                instance_ids=instance_ids,
                variant_tables=variant_tables,
                logical_net_families=tuple(
                    (
                        instance_ids[source].family_id,
                        instance_ids[destination].family_id,
                    )
                    for source, destination in nets
                ),
            )
            for height in heights
        }
    finally:
        telemetry.planning_time_s += time.monotonic() - planning_started
    selected_cache: dict[
        tuple[tuple[StripInstanceId, ...], tuple[int, ...]],
        tuple[Strip, ...],
    ] = {}
    direct_cache: dict[
        tuple[tuple[StripInstanceId, ...], tuple[int, ...]],
        tuple[DirectInsertTarget, ...],
    ] = {}

    def selected_strips(
        problem: PlacementProblem,
        variant_indices: tuple[int, ...],
    ) -> tuple[Strip, ...]:
        key = (problem.instance_ids, variant_indices)
        selected = selected_cache.get(key)
        if selected is None:
            selected = tuple(_selected_strips(strips, problem, variant_indices))
            selected_cache[key] = selected
        return selected

    def selected_direct_targets(
        problem: PlacementProblem,
        variant_indices: tuple[int, ...],
    ) -> tuple[DirectInsertTarget, ...]:
        key = (problem.instance_ids, variant_indices)
        targets = direct_cache.get(key)
        if targets is None:
            selected = selected_strips(problem, variant_indices)
            targets = _direct_alignment_targets(_direct_net_candidates(list(selected), spec))
            direct_cache[key] = targets
        return targets

    def direct_targets_for_state(
        problem: PlacementProblem,
        state: AnnealState,
    ) -> tuple[DirectInsertTarget, ...]:
        return selected_direct_targets(problem, state.variant_indices)

    def prepare(height: int, decoded: DecodedPlacement) -> _ProductionCandidate:
        preparation_started = time.monotonic()
        try:
            problem = problems[height]
            selected = selected_strips(problem, decoded.variant_indices)
            selected_targets = selected_direct_targets(
                problem,
                decoded.variant_indices,
            )
            aligned = align_direct_inserts(problem, decoded, selected_targets)
            pack = _decoded_pack(height, aligned)
            if deadline_reached():
                return _ProductionCandidate(
                    height=height,
                    problem=problem,
                    decoded=aligned,
                    pack=pack,
                    prepared=None,
                    preparation_error="deadline",
                    selected_strips=selected,
                )
            try:
                prepared = _prepare_routing_problem(
                    spec,
                    list(selected),
                    pack,
                    power=power,
                )
            except _Unpowerable:
                return _ProductionCandidate(
                    height=height,
                    problem=problem,
                    decoded=aligned,
                    pack=pack,
                    prepared=None,
                    preparation_error="unpowerable",
                    selected_strips=selected,
                )
            return _ProductionCandidate(
                height=height,
                problem=problem,
                decoded=aligned,
                pack=pack,
                prepared=prepared,
                selected_strips=selected,
            )
        finally:
            telemetry.preparation_time_s += time.monotonic() - preparation_started

    def global_route(
        candidate: _ProductionCandidate,
        feedback: FeedbackState,
        allowance: int,
    ) -> GlobalRouteResult:
        telemetry.global_routes += 1
        telemetry.feedback_nets = max(telemetry.feedback_nets, len(feedback.net_weight))
        telemetry.feedback_cells = max(telemetry.feedback_cells, len(feedback.cell_history))
        if candidate.prepared is None:
            is_deadline = candidate.preparation_error == "deadline"
            return _empty_global_result(
                exhausted=False,
                cancelled=is_deadline,
            )
        routing_started = time.monotonic()
        try:
            if deadline_reached():
                result = _empty_global_result(exhausted=False, cancelled=True)
            else:
                current_nets = tuple(net.net_id for net in candidate.prepared.nets)
                expected_weights = {
                    net: weight
                    for net in current_nets
                    if (
                        weight := feedback.logical_net_weight.get(
                            net.logical,
                            0.0,
                        )
                    )
                    > 0.0
                }
                routed_feedback = (
                    feedback
                    if dict(feedback.net_weight) == expected_weights
                    else remap_feedback_nets(feedback, current_nets)
                )
                result = route_global(
                    candidate.prepared,
                    routed_feedback,
                    allowance,
                    max_rounds=config.global_rounds,
                    cancelled=deadline_reached,
                )
        finally:
            telemetry.global_route_time_s += time.monotonic() - routing_started
        telemetry.global_expansions += result.expansions
        telemetry.best_overflow = (
            result.total_overflow
            if telemetry.best_overflow is None
            else min(telemetry.best_overflow, result.total_overflow)
        )
        return result

    def detailed_route(candidate: _ProductionCandidate, allowance: int) -> DetailedStageResult:
        telemetry.detailed_routes += 1
        if candidate.preparation_error == "deadline" or deadline_reached():
            return _closed_detailed_result(DetailedRouteStatus.BUDGET)
        if candidate.prepared is None:
            return _closed_detailed_result(DetailedRouteStatus.UNPOWERABLE)
        routing_started = time.monotonic()
        try:
            result = _route_detailed_candidate(
                spec,
                list(candidate.selected_strips) if candidate.selected_strips else strips,
                candidate.prepared,
                power=power,
                deadline=deadline,
                allowance=allowance,
            )
        finally:
            telemetry.detailed_route_time_s += time.monotonic() - routing_started
        telemetry.detailed_expansions += result.routing.expansions
        telemetry.best_stranded = (
            result.routing.failed_count
            if telemetry.best_stranded is None
            else min(telemetry.best_stranded, result.routing.failed_count)
        )
        if result.routing.status is DetailedRouteStatus.ROUTED:
            telemetry.elevated_coater_routes = max(
                telemetry.elevated_coater_routes,
                len(candidate.prepared.coater_supply_ports),
            )
        return result

    def certify(placement: Placement) -> ValidationVerdict:
        validation_started = time.monotonic()
        try:
            if deadline_reached():
                return ValidationVerdict(False, ("deadline",))
            report = validate.certify(placement, spec, expect_power=power)
            if deadline_reached():
                return ValidationVerdict(False, ("deadline",))
            failures = tuple(sorted({finding.check for finding in report.errors}))
            return ValidationVerdict(not failures, failures)
        finally:
            telemetry.validation_time_s += time.monotonic() - validation_started

    family_by_id = {family.family_id: family for family in generate_strip_families(spec)}
    telemetry.pose_feasibility_rejects = sum(
        4 - len({variant.yaw for variant in family.variants}) for family in family_by_id.values()
    )

    def split_stage(
        height: int,
        problem: PlacementProblem,
        state: AnnealState,
        _feedback: FeedbackState,
        result: DetailedRouteResult,
        stagnation: int,
    ) -> StageBoundaryUpdate | None:
        target = select_split_candidate(
            result,
            problem.instance_ids,
            stagnation=stagnation,
            split_after=2,
        )
        if target is None:
            return None
        family = family_by_id[problem.instance_ids[target].family_id]
        transformed = split_stage_boundary(
            problem,
            state,
            family,
            target,
            right_variant_offset=1 if len(family.variants) > 1 else 0,
        )
        selected = _selected_strips(
            strips,
            transformed.problem,
            transformed.state.variant_indices,
        )
        rebuilt = _rebuild_stage_problem_nets(
            transformed.problem,
            tuple(_nets_between(selected)),
        )
        problems[height] = rebuilt
        selected_cache.clear()
        direct_cache.clear()
        return StageBoundaryUpdate(rebuilt, transformed.state)

    expansion_total = max(
        _ROUTING_BUDGET,
        int(_ROUTING_EXPANSIONS_PER_SECOND * ceiling),
    )
    solver = SequenceSolver(
        heights=heights,
        problem_for_height=problems.__getitem__,
        adapters=StageAdapters(
            prepare=prepare,
            global_route=global_route,
            detailed_route=detailed_route,
            validate=certify,
        ),
        expansion_budget=ExpansionBudget(expansion_total),
        config=config,
        deadline_reached=deadline_reached,
        direct_targets=direct_targets,
        direct_targets_for_state=direct_targets_for_state,
        stage_boundary_transform=split_stage,
    )
    return _ProductionRun(
        solver=solver,
        telemetry=telemetry,
        heights=heights,
        direct_candidates=len(direct_candidates),
        started=started,
        ceiling=ceiling,
    )


def _decoded_pack(height: int, decoded: DecodedPlacement) -> _Pack:
    """Convert decoded box origins to freeform content origins exactly once."""
    return _Pack(
        at={
            index: (x + WEST_CHANNEL, y)
            for index, (x, y) in enumerate(zip(decoded.x, decoded.y, strict=True))
        },
        width=decoded.width,
        height=height,
        status="sequence-pair",
        direct=decoded.direct,
    )


class _SolverFactory(Protocol):
    def __call__(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float,
        power: bool,
        strip_len: int,
        config: SequenceSolverConfig,
    ) -> SequenceSolver[Any]: ...


class SequencePairLayout:
    """Audit-only closed-loop sequence-pair layout backend."""

    name = "sequence-pair"

    def __init__(
        self,
        *,
        power: bool = False,
        strip_len: int = 6,
        config: SequenceSolverConfig | None = None,
        solver_factory: _SolverFactory | None = None,
    ) -> None:
        if type(power) is not bool:
            raise ValueError("power mode must be a bool")
        if type(strip_len) is not int or strip_len <= 0:
            raise ValueError("strip length must be a positive integer")
        self._solver_factory = solver_factory
        self.power = power
        self.strip_len = strip_len
        self.config = config or SequenceSolverConfig()

    def lay_out(self, spec: BuildSpec, *, time_budget_s: float = 60.0) -> Placement:
        """Return only a detailed-routed, powered, validator-clean placement."""
        if time_budget_s <= 0:
            raise NoValidLayout(
                "no time budget was given, so the sequence search was never asked",
                spec_label=spec.label,
                budget_s=time_budget_s,
            )
        if self._solver_factory is not None:
            solver = self._solver_factory(
                spec,
                time_budget_s=time_budget_s,
                power=self.power,
                strip_len=self.strip_len,
                config=self.config,
            )
            return solver.search().placement

        run = _production_run(
            spec,
            time_budget_s=time_budget_s,
            power=self.power,
            strip_len=self.strip_len,
            config=self.config,
        )
        try:
            result = run.solver.search()
        except NoValidLayout as exc:
            raise NoValidLayout(
                exc.reason,
                spec_label=spec.label,
                budget_s=run.ceiling,
            ) from exc
        return _with_observational_stats(result, run, self.power, self.config)


def _with_observational_stats(
    result: SequenceSearchResult,
    run: _ProductionRun,
    power: bool,
    config: SequenceSolverConfig,
) -> Placement:
    placement = result.placement
    telemetry = run.telemetry
    total_time_s = time.monotonic() - run.started
    adapter_time_s = (
        telemetry.planning_time_s
        + telemetry.preparation_time_s
        + telemetry.global_route_time_s
        + telemetry.detailed_route_time_s
        + telemetry.validation_time_s
    )
    stage_count = len(result.stages)
    lns_sizes = tuple(stage.lns_size for stage in result.stages)
    belt_tiles = _exact_key(placement)[1]
    exact_stage = next(
        (stage for stage in result.stages if stage.exact_key == result.exact_key),
        None,
    )
    pose_yaws = exact_stage.selected_pose_yaws if exact_stage is not None else ()
    pose_counts = {
        yaw: sum(selected == yaw for selected in pose_yaws) for yaw in (0.0, 90.0, 180.0, 270.0)
    }
    stats: dict[str, object] = dict(placement.stats)
    stats.update(
        {
            "backend": "sequence-pair",
            "accelerator": "python",
            "seed": float(config.seed),
            "seeds": float(len({stage.seed for stage in result.stages})),
            "heights": float(len(run.heights)),
            "restarts": float(len(run.heights) * config.restarts_per_height),
            "stages": float(stage_count),
            "moves": float(stage_count * config.moves_per_stage),
            "accepted_moves": float(sum(stage.accepted_moves for stage in result.stages)),
            "decoded_candidates": float(sum(stage.global_routes for stage in result.stages)),
            "global_routes": float(telemetry.global_routes),
            "detailed_routes": float(telemetry.detailed_routes),
            "best_overflow": float(telemetry.best_overflow or 0),
            "best_stranded": float(telemetry.best_stranded or 0),
            "lns_invocations": float(sum(size > 0 for size in lns_sizes)),
            "lns_total_size": float(sum(lns_sizes)),
            "lns_max_size": float(max(lns_sizes, default=0)),
            "feedback_nets": float(telemetry.feedback_nets),
            "feedback_cells": float(telemetry.feedback_cells),
            "feedback_decays": float(stage_count),
            "variant_moves": float(sum(stage.variant_moves for stage in result.stages)),
            "pose_count": float(len(pose_yaws)),
            "pose_yaw_0": float(pose_counts[0.0]),
            "pose_yaw_90": float(pose_counts[90.0]),
            "pose_yaw_180": float(pose_counts[180.0]),
            "pose_yaw_270": float(pose_counts[270.0]),
            "split_count": float(sum(stage.split_count for stage in result.stages)),
            "merge_count": float(sum(stage.merge_count for stage in result.stages)),
            "pose_feasibility_rejects": float(telemetry.pose_feasibility_rejects),
            "elevated_coater_routes": float(telemetry.elevated_coater_routes),
            "planning_time_s": telemetry.planning_time_s,
            "placement_time_s": max(0.0, total_time_s - adapter_time_s),
            "preparation_time_s": telemetry.preparation_time_s,
            "global_route_time_s": telemetry.global_route_time_s,
            "detailed_route_time_s": telemetry.detailed_route_time_s,
            "validation_time_s": telemetry.validation_time_s,
            "compilation_time_s": 0.0,
            "total_time_s": total_time_s,
            "global_expansions": float(telemetry.global_expansions),
            "detailed_expansions": float(telemetry.detailed_expansions),
            "expansions": float(run.solver.budget.spent),
            "expansion_allowance": float(run.solver.budget.total),
            "final_reserved": float(run.solver.budget.final_reserved),
            "cache_hits": 0.0,
            "direct_candidates": float(run.direct_candidates),
            "direct_inserts": float(placement.stats.get("direct_inserts", 0.0)),
            "area": float(placement.area),
            "belt_tiles": float(belt_tiles),
            "power": float(power),
            "termination": result.termination,
            "termination_cause": result.termination,
            "validation_clean": 1.0,
            "validation_status": "clean",
        }
    )
    # Placement predates string-valued audit dimensions.  Keep the public
    # runtime contract required by the audit backend without widening the shared
    # production type in this audit-only task.
    return replace(placement, stats=cast(dict[str, float], stats))
