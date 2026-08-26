"""Deterministic staged orchestration for sequence-pair routing search.

The generic scheduler keeps proxy placement, relaxed routing, detailed
emission, and exact acceptance separate.  The public layout binds those stages
to the current freeform geometry, routers, power planner, and validator.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from fractions import Fraction
from types import MappingProxyType
from typing import Any, Protocol, cast

from flab2bp.layout import validate
from flab2bp.layout.base import RETRY_BUDGET_S, NoValidLayout, Placement
from flab2bp.layout.compact_seed import (
    CompactSeedConfig,
    CompactSeedDiagnostics,
    CompactSeedResult,
    CompactSeedStatus,
    VariantDirectInsertTarget,
    solve_compact_seed,
)
from flab2bp.layout.freeform import (
    _ROUTING_BUDGET,
    _ROUTING_EXPANSIONS_PER_SECOND,
    WEST_CHANNEL,
    Strip,
    _box,
    _build_prepared,
    _candidate_heights,
    _coarsen_saturated_strip_plan,
    _dests,
    _direct_alignment_targets,
    _direct_net_candidates,
    _fanout_shortfall,
    _greedy_pack,
    _Pack,
    _prepare_routing_problem,
    _PreparedRoutingProblem,
    _Unpowerable,
    _Unseatable,
    plan_strips,
)
from flab2bp.layout.global_router import GlobalRouteResult, route_global
from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    LogicalNetId,
    NetRole,
    RouteFailureKind,
    decay_feedback,
    feedback_cost_context,
    geometric_failure_instances,
    remap_feedback_nets,
    select_lns_neighbourhood,
    select_split_candidate,
    update_feedback,
)
from flab2bp.layout.sequence_kernel import BackendName, build_sequence_kernel
from flab2bp.layout.sequence_pair import (
    TOPOLOGY_MOVE_KINDS,
    AnnealConfig,
    AnnealIncumbent,
    AnnealStageResult,
    AnnealState,
    DecodedPlacement,
    DirectInsertTarget,
    EliteCategory,
    EnergyBreakdown,
    GapProfile,
    PlacementKey,
    PlacementProblem,
    SearchEnergy,
    StageBoundaryUpdate,
    TaggedAnnealIncumbent,
    align_direct_inserts,
    anneal_stage,
    build_elite_archive,
    decode_state,
    derive_stage_seed,
    merge_stage_boundary,
    quality_archive_key,
    repair_neighbourhood,
    split_stage_boundary,
)
from flab2bp.layout.strip_variants import (
    StripFamily,
    StripFamilyId,
    StripInstanceId,
    StripVariant,
    StripVariantId,
    default_strip_variant,
    generate_strip_families,
    partition_strip_family,
    variants_for_count,
)
from flab2bp.spec import BuildSpec


class ObjectiveMode(StrEnum):
    """Per-height objective used for routing cadence and archive exploitation."""

    EXPLORATION = "exploration"
    QUALITY = "quality"


type QualityArchiveKey = tuple[int, int, int, int, float, PlacementKey]

_QUALITY_REVISIT_AFTER = 2
_MAX_SEQUENCE_ISLANDS = 16
_COMPACT_SEED_DETERMINISTIC_SECONDS_PER_BUDGET_SECOND = 1.0 / 15.0
_COMPACT_SEED_WALL_SHARE = Fraction(1, 3)
_COMPACT_SEED_DIRECT_MIN_BUDGET_S = 30.0
_DENSE_SPRAY_MACHINE_THRESHOLD = 90
_DENSE_SPRAY_LANE_THRESHOLD = 10
_DENSE_SPRAY_COMPACT_SEED_ATTEMPT = 4
_COMPACT_LARGE_VARIANT_SIZE = 40
_COMPACT_LARGE_VARIANT_DETERMINISTIC_CAP = 0.5


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


def _budgeted_compact_seed_config(
    time_budget_s: float,
    requested: CompactSeedConfig,
) -> CompactSeedConfig:
    """Cap CP seed work so a short solve retains most of its wall for routing."""
    ceiling = max(time_budget_s, RETRY_BUDGET_S)
    deterministic_limit = min(
        requested.max_deterministic_time,
        ceiling * _COMPACT_SEED_DETERMINISTIC_SECONDS_PER_BUDGET_SECOND,
    )
    return replace(
        requested,
        max_deterministic_time=float(deterministic_limit),
    )


def _serial_compact_seed_attempt(machine_count: int, sprayed_lanes: int) -> int:
    """Select the measured dense-spray topology without probing inside the budget."""
    return (
        _DENSE_SPRAY_COMPACT_SEED_ATTEMPT
        if machine_count >= _DENSE_SPRAY_MACHINE_THRESHOLD
        and sprayed_lanes >= _DENSE_SPRAY_LANE_THRESHOLD
        else 0
    )


@dataclass(slots=True)
class ExpansionBudget:
    """One deterministic ledger with a proxy-inaccessible closure reserve."""

    total: int
    discovery_by_height: dict[int, int] = field(default_factory=dict, init=False)
    shared_left: int = field(init=False)
    final_reserved: int = field(init=False)
    final_left: int = field(init=False)
    _spent: int = field(default=0, init=False, repr=False)
    _unsettled_discovery: set[int] = field(default_factory=set, init=False, repr=False)
    _discovery_spent: dict[int, int] = field(default_factory=dict, init=False, repr=False)
    _pending_discovery_return: int = field(default=0, init=False, repr=False)
    _configured: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.total) is not int or self.total < 0:
            raise ValueError("total expansion budget must be a non-negative integer")
        self.final_reserved = _fraction_ceiling(self.total, Fraction(1, 4))
        self.final_left = self.final_reserved
        self.shared_left = self.total - self.final_reserved

    @property
    def spent(self) -> int:
        """Expansions charged exactly once across every routing role."""
        return self._spent

    @property
    def searchable_total(self) -> int:
        """Budget visible to discovery/proxy stages before authoritative borrowing."""
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
        self.final_left = self.final_reserved
        searchable = self.total - self.final_reserved
        discovery_slice, remainder = divmod(searchable, len(heights))
        self.discovery_by_height = {height: discovery_slice for height in heights}
        self.shared_left = remainder
        self._unsettled_discovery = set(heights)
        self._discovery_spent = dict.fromkeys(heights, 0)
        self._configured = True

    def discovery_allowance(self, height: int) -> int:
        if height not in self._unsettled_discovery:
            raise ValueError("height has no unsettled discovery reservation")
        return self.discovery_by_height[height] - self._discovery_spent[height]

    def charge_discovery(self, height: int, spent: int) -> None:
        """Charge part of one height reservation without closing discovery."""
        allowance = self.discovery_allowance(height)
        _check_spend(spent, allowance)
        self._discovery_spent[height] += spent
        self._spent += spent

    def detailed_discovery_allowance(self, height: int) -> int:
        """All remaining work, exposed only to one authoritative seed closure."""
        self.discovery_allowance(height)
        return (
            sum(
                self.discovery_allowance(candidate)
                for candidate in self.discovery_by_height
                if candidate in self._unsettled_discovery
            )
            + self.final_left
            + self.shared_left
        )

    def charge_detailed_discovery(self, height: int, spent: int) -> None:
        """Atomically charge closure without exposing borrowed work to proxies."""
        _check_spend(spent, self.detailed_discovery_allowance(height))
        remaining = spent

        current = self.discovery_allowance(height)
        take = min(remaining, current)
        self._discovery_spent[height] += take
        remaining -= take

        take = min(remaining, self.final_left)
        self.final_left -= take
        remaining -= take

        for candidate in self.discovery_by_height:
            if remaining == 0:
                break
            if candidate == height or candidate not in self._unsettled_discovery:
                continue
            allowance = self.discovery_allowance(candidate)
            take = min(remaining, allowance)
            self._discovery_spent[candidate] += take
            remaining -= take

        take = min(remaining, self.shared_left)
        self.shared_left -= take
        remaining -= take
        if remaining:
            raise AssertionError("detailed closure charge exceeded decomposed budget")
        self._spent += spent

    def settle_detailed_discovery(self, height: int, spent: int) -> None:
        """Close one discovery after its authoritative route borrowed future work."""
        self.charge_detailed_discovery(height, spent)
        self._pending_discovery_return += self.discovery_allowance(height)
        self._unsettled_discovery.remove(height)
        if not self._unsettled_discovery:
            self.shared_left += self._pending_discovery_return
            self._pending_discovery_return = 0

    def settle_discovery(self, height: int, spent: int) -> None:
        allowance = self.discovery_allowance(height)
        _check_spend(spent, allowance)
        self.charge_discovery(height, spent)
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
class StageObservation:
    """Deterministic observations from one closed temperature stage."""

    height: int
    restart: int
    stage_index: int
    seed: int
    accepted_moves: int
    anneal_stages: int
    anneal_moves: int
    anneal_seeds: tuple[int, ...]
    global_routes: int
    backend: BackendName = field(compare=False)
    global_overflow: int | None
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
    candidate_key: PlacementKey
    breakdown: EnergyBreakdown
    archive_categories: tuple[EliteCategory, ...]
    preparation_time_s: float = field(compare=False)
    global_route_time_s: float = field(compare=False)
    detailed_route_time_s: float = field(compare=False)
    validation_time_s: float = field(compare=False)
    objective_mode: ObjectiveMode
    global_skip_reason: str | None
    quality_entered: bool
    quality_exited: bool
    stagnation_count: int

    @property
    def energy(self) -> SearchEnergy:
        """Return the exact blended energy derived from the observed components."""
        return self.breakdown.energy


@dataclass(frozen=True, slots=True)
class SequenceSearchResult:
    """Only an exact, detailed-routed, validator-clean incumbent."""

    placement: Placement
    exact_key: tuple[int, int]
    exact_candidate_key: PlacementKey
    exact_breakdown: EnergyBreakdown
    exact_archive_categories: tuple[EliteCategory, ...]
    stages: tuple[StageObservation, ...]
    termination: str

    @property
    def exact_energy(self) -> SearchEnergy:
        """Return the selected exact incumbent's observed blended energy."""
        return self.exact_breakdown.energy


@dataclass(slots=True)
class _RestartState:
    restart: int
    seed: int
    anneal: AnnealState
    accepted_moves: int = 0
    archive: tuple[TaggedAnnealIncumbent, ...] = ()
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
    routing_seed: AnnealState | None = None
    routing_seed_closed: bool = False
    stages: int = 0
    spent: int = 0
    stranded: int = 1 << 60
    global_overflow: int = 1 << 60
    estimated_area: int = 1 << 60
    exact_key: tuple[int, int] | None = None
    objective_mode: ObjectiveMode = ObjectiveMode.EXPLORATION
    narrowest_key: QualityArchiveKey | None = None
    quality_stagnation: int = 0
    quality_restart: int | None = None
    pending_quality_exit: bool = False


@dataclass(frozen=True, slots=True)
class _ExactIncumbent:
    exact_key: tuple[int, int]
    placement: Placement
    candidate_key: PlacementKey
    breakdown: EnergyBreakdown
    archive_categories: tuple[EliteCategory, ...]


@dataclass(frozen=True, slots=True)
class _AnnealedRestart:
    restart: _RestartState
    stage_start: AnnealState
    result: AnnealStageResult


@dataclass(frozen=True, slots=True)
class _RoutingObservation:
    restart: _RestartState
    stage_index: int
    backend: BackendName
    continue_search: bool


@dataclass(frozen=True, slots=True)
class _StageCandidate[PreparedT]:
    prepared: PreparedT
    source: _AnnealedRestart | None
    state: AnnealState
    decoded: DecodedPlacement
    key: PlacementKey
    breakdown: EnergyBreakdown
    archive_categories: tuple[EliteCategory, ...]
    anneal_stages: int
    anneal_moves: int
    accepted_moves: int
    anneal_seeds: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _GlobalCandidate[PreparedT](_StageCandidate[PreparedT]):
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
StageBoundaryCommit = Callable[[int, PlacementProblem], None]


class SequenceSolver[PreparedT]:
    """Run deterministic discovery, then best-first closed routing stages."""

    def __init__(
        self,
        *,
        heights: tuple[int, ...],
        problem_for_height: Callable[[int], PlacementProblem],
        adapters: StageAdapters[PreparedT],
        expansion_budget: ExpansionBudget,
        protected_followup_heights: tuple[int, ...] = (),
        config: SequenceSolverConfig | None = None,
        deadline_reached: Callable[[], bool] | None = None,
        initial_feedback: Callable[[PlacementProblem], FeedbackState] | None = None,
        initial_states: Mapping[int, AnnealState] | None = None,
        direct_targets: tuple[DirectInsertTarget, ...] = (),
        direct_targets_for_state: Callable[
            [PlacementProblem, AnnealState], tuple[DirectInsertTarget, ...]
        ]
        | None = None,
        stage_boundary_transform: StageBoundaryTransform | None = None,
        stage_boundary_commit: StageBoundaryCommit | None = None,
        borrow_first_discovery: bool = False,
    ) -> None:
        if (
            not isinstance(heights, tuple)
            or not heights
            or len(set(heights)) != len(heights)
            or any(type(height) is not int or height <= 0 for height in heights)
        ):
            raise ValueError("candidate heights must be unique positive integers in a tuple")
        if (
            not isinstance(protected_followup_heights, tuple)
            or len(set(protected_followup_heights)) != len(protected_followup_heights)
            or any(
                type(height) is not int or height not in heights
                for height in protected_followup_heights
            )
        ):
            raise ValueError(
                "protected follow-up heights must be unique scheduled integers in a tuple"
            )
        if type(borrow_first_discovery) is not bool:
            raise ValueError("borrow-first-discovery mode must be a bool")
        self.config = config or SequenceSolverConfig()
        self.adapters = adapters
        self.budget = expansion_budget
        self.deadline_reached = deadline_reached or (lambda: False)
        if not isinstance(direct_targets, tuple):
            raise ValueError("direct-insert targets must be an immutable tuple")
        self.direct_targets = direct_targets
        self.stage_boundary_transform = stage_boundary_transform
        self.stage_boundary_commit = stage_boundary_commit
        self.direct_targets_for_state = direct_targets_for_state
        problem_by_height = {height: problem_for_height(height) for height in heights}
        self.initial_states = _validated_initial_states(
            problem_by_height,
            initial_states,
        )
        self.budget.configure(heights, self.config.final_reserve_fraction)
        self._protected_followup_heights = protected_followup_heights
        self._borrow_first_discovery = borrow_first_discovery
        feedback_factory = initial_feedback or _default_feedback
        self._heights = [
            _new_height_state(
                order,
                height,
                problem_by_height[height],
                feedback_factory,
                self.config,
                self.initial_states.get(height),
            )
            for order, height in enumerate(heights)
        ]
        self._stage_stats: list[StageObservation] = []
        self._incumbent: _ExactIncumbent | None = None
        self._last_height: int | None = None

    def search(self, *, max_stages: int | None = None) -> SequenceSearchResult:
        """Search until its stage cap, deadline, or searchable budget is exhausted."""
        stage_limit = (
            (1 + (self.config.stages - 1) * self.config.restarts_per_height) * len(self._heights)
            + sum(height.routing_seed is not None for height in self._heights)
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
            seed_height = next(
                (
                    height
                    for height in self._heights
                    if height.routing_seed is not None and not height.routing_seed_closed
                ),
                None,
            )
            if seed_height is not None:
                seed_height.routing_seed_closed = True
                allowance = self.budget.detailed_discovery_allowance(seed_height.height)
                spent, cancelled = self._route_seed_closure(seed_height, allowance)
                self.budget.charge_detailed_discovery(seed_height.height, spent)
                self._last_height = seed_height.height
                if cancelled:
                    termination = "cancelled"
                    break
                if self.deadline_reached():
                    termination = "deadline"
                    break
                continue

            discovery = next((height for height in self._heights if height.stages == 0), None)
            if discovery is not None:
                height_state = discovery
                allowance = self.budget.discovery_allowance(height_state.height)
                if self._borrow_first_discovery:
                    closure_allowance = self.budget.detailed_discovery_allowance(
                        height_state.height
                    )
                    spent, cancelled = self._run_discovery(
                        height_state,
                        allowance,
                        closure_allowance=closure_allowance,
                    )
                    self.budget.settle_detailed_discovery(
                        height_state.height,
                        spent,
                    )
                    self._borrow_first_discovery = False
                else:
                    spent, cancelled = self._run_discovery(height_state, allowance)
                    self.budget.settle_discovery(height_state.height, spent)
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
                protected_followup = next(
                    (
                        height
                        for height in eligible
                        if height.height in self._protected_followup_heights and height.stages == 1
                    ),
                    None,
                )
                height_state = protected_followup or self._select_height(eligible)
                allowance = self.budget.shared_allowance()
                restart = self._select_restart(height_state)
                spent, cancelled = self._run_stage(height_state, restart, allowance)
                self.budget.settle_shared(spent)
            self._last_height = height_state.height
            if cancelled:
                termination = "cancelled"
                break
            if self.deadline_reached():
                termination = "deadline"
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
        incumbent = self._incumbent
        return SequenceSearchResult(
            placement=incumbent.placement,
            exact_key=incumbent.exact_key,
            exact_candidate_key=incumbent.candidate_key,
            exact_breakdown=incumbent.breakdown,
            exact_archive_categories=incumbent.archive_categories,
            stages=tuple(self._stage_stats),
            termination=termination,
        )

    def _select_height(self, eligible: Sequence[_HeightState]) -> _HeightState:
        """Choose best-first, forcing one deterministic revisit after stagnation."""
        best = min(eligible, key=_height_priority)
        if self._last_height == best.height and best.quality_stagnation >= _QUALITY_REVISIT_AFTER:
            alternatives = tuple(height for height in eligible if height is not best)
            if alternatives:
                return min(alternatives, key=_height_priority)
        return best

    def _select_restart(self, height_state: _HeightState) -> _RestartState:
        if height_state.objective_mode is ObjectiveMode.QUALITY:
            quality_restart = self._select_quality_restart(height_state)
            if quality_restart is not None:
                return quality_restart
            height_state.objective_mode = ObjectiveMode.EXPLORATION
            height_state.quality_restart = None
            height_state.quality_stagnation = 0
            height_state.pending_quality_exit = True
        return min(
            (restart for restart in height_state.restarts if restart.stages < self.config.stages),
            key=lambda restart: (restart.stages, restart.restart),
        )

    def _select_quality_restart(self, height_state: _HeightState) -> _RestartState | None:
        legal: list[tuple[_RestartState, AnnealIncumbent]] = []
        for restart in height_state.restarts:
            if restart.stages >= self.config.stages:
                continue
            candidate = _legal_quality_candidate(restart.archive)
            if candidate is not None:
                legal.append((restart, candidate))
        if not legal:
            return None

        selected = next(
            (entry for entry in legal if entry[0].restart == height_state.quality_restart),
            None,
        )
        if selected is None:
            selected = min(
                legal,
                key=lambda entry: (
                    quality_archive_key(entry[1]),
                    entry[0].stages,
                    entry[0].restart,
                ),
            )
        restart, candidate = selected
        restart.anneal = replace(
            candidate.state,
            base_seed=restart.seed,
            stage_index=restart.anneal.stage_index,
        )
        height_state.quality_restart = restart.restart
        return restart

    def _route_seed_closure(
        self,
        height_state: _HeightState,
        allowance: int,
    ) -> tuple[int, bool]:
        """Score and authoritatively route one raw seed before any annealing."""
        state = height_state.routing_seed
        if state is None:
            raise ValueError("seed closure requires one validated routing seed")
        problem = height_state.problem
        context = feedback_cost_context(
            height_state.feedback,
            problem,
            self.direct_targets,
        )
        kernel = build_sequence_kernel(problem, context)
        direct_targets = (
            self.direct_targets
            if self.direct_targets_for_state is None
            else self.direct_targets_for_state(problem, state)
        )
        incumbent = kernel.score_state(state, direct_targets=direct_targets)
        tagged = build_elite_archive((incumbent,), 1)[0]
        preparation_started = time.perf_counter()
        prepared = self.adapters.prepare(height_state.height, incumbent.decoded)
        preparation_time_s = time.perf_counter() - preparation_started
        selected = _StageCandidate(
            prepared=prepared,
            source=None,
            state=incumbent.state,
            decoded=incumbent.decoded,
            key=incumbent.key,
            breakdown=incumbent.breakdown,
            archive_categories=tagged.categories,
            anneal_stages=0,
            anneal_moves=0,
            accepted_moves=0,
            anneal_seeds=(),
        )
        detailed_started = time.perf_counter()
        detailed = self.adapters.detailed_route(prepared, allowance)
        detailed_route_time_s = time.perf_counter() - detailed_started
        spent = detailed.routing.expansions
        _check_spend(spent, allowance)
        return self._complete_routing_stage(
            height_state,
            selected,
            detailed,
            spent,
            observation=_RoutingObservation(
                restart=height_state.restarts[0],
                stage_index=0,
                backend=kernel.backend,
                continue_search=False,
            ),
            global_routes=0,
            global_overflow=None,
            global_skip_reason="compact-seed",
            preparation_time_s=preparation_time_s,
            global_route_time_s=0.0,
            detailed_route_time_s=detailed_route_time_s,
        )

    def _run_discovery(
        self,
        height_state: _HeightState,
        allowance: int,
        *,
        closure_allowance: int | None = None,
    ) -> tuple[int, bool]:
        """Advance every restart, then route their deterministic archive union once."""
        annealed = self._anneal_restarts(height_state, height_state.restarts)
        self._persist_annealed_restarts(annealed)
        return self._route_annealed(
            height_state,
            annealed,
            allowance,
            closure_allowance=closure_allowance,
        )

    def _run_stage(
        self,
        height_state: _HeightState,
        restart: _RestartState,
        allowance: int,
    ) -> tuple[int, bool]:
        annealed = self._anneal_restarts(height_state, (restart,))
        self._persist_annealed_restarts(annealed)
        return self._route_annealed(height_state, annealed, allowance)

    def _anneal_restarts(
        self,
        height_state: _HeightState,
        restarts: Sequence[_RestartState],
    ) -> tuple[_AnnealedRestart, ...]:
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
        topology_stage_config = (
            replace(stage_config, move_kinds=TOPOLOGY_MOVE_KINDS)
            if self.config.restarts_per_height >= 2
            else stage_config
        )
        results: list[_AnnealedRestart] = []
        for restart in restarts:
            topology_lane = self.config.restarts_per_height >= 2 and restart.restart == 0
            restart_config = topology_stage_config if topology_lane else stage_config
            stage_start = restart.anneal
            if topology_lane:
                stage_start = replace(
                    stage_start,
                    gaps=GapProfile.zero(problem.size),
                    variant_indices=(0,) * problem.size,
                )
            if self.direct_targets_for_state is None:
                result = anneal_stage(
                    problem,
                    stage_start,
                    restart_config,
                    context,
                )
            else:
                result = anneal_stage(
                    problem,
                    stage_start,
                    restart_config,
                    context,
                    direct_targets_for_state=self.direct_targets_for_state,
                )
            results.append(
                _AnnealedRestart(
                    restart=restart,
                    stage_start=stage_start,
                    result=result,
                )
            )
        return tuple(results)

    @staticmethod
    def _persist_annealed_restarts(annealed: Sequence[_AnnealedRestart]) -> None:
        for source in annealed:
            source.restart.anneal = source.result.final_state
            source.restart.accepted_moves += source.result.accepted_moves
            source.restart.archive = source.result.archive
            source.restart.stages += 1

    def _route_annealed(
        self,
        height_state: _HeightState,
        annealed: Sequence[_AnnealedRestart],
        allowance: int,
        *,
        closure_allowance: int | None = None,
    ) -> tuple[int, bool]:
        source_by_incumbent: dict[int, _AnnealedRestart] = {}
        for source in annealed:
            for tagged in source.result.archive:
                # Archive union retains an input object, so identity carries its restart.
                source_by_incumbent.setdefault(id(tagged.incumbent), source)
        merged = build_elite_archive(
            (tagged.incumbent for source in annealed for tagged in source.result.archive),
            self.config.global_elites,
        )
        narrowest = next(
            tagged for tagged in merged if EliteCategory.NARROWEST in tagged.categories
        )
        height_state.narrowest_key = quality_archive_key(narrowest.incumbent)
        candidates = tuple((tagged, source_by_incumbent[id(tagged.incumbent)]) for tagged in merged)
        if height_state.objective_mode is ObjectiveMode.QUALITY:
            if narrowest.incumbent.breakdown.hard_outline_overflow == 0:
                return self._route_quality_candidate(
                    height_state,
                    narrowest,
                    source_by_incumbent[id(narrowest.incumbent)],
                    annealed,
                    allowance,
                )
            height_state.objective_mode = ObjectiveMode.EXPLORATION
            height_state.quality_restart = None
            height_state.quality_stagnation = 0
            height_state.pending_quality_exit = True
        return self._route_archive(
            height_state,
            candidates,
            annealed,
            allowance,
            closure_allowance=closure_allowance,
        )

    def _route_quality_candidate(
        self,
        height_state: _HeightState,
        tagged: TaggedAnnealIncumbent,
        source: _AnnealedRestart,
        annealed: Sequence[_AnnealedRestart],
        allowance: int,
    ) -> tuple[int, bool]:
        """Detailed-route one legal width-first candidate without a proxy pass."""
        elite = tagged.incumbent
        preparation_started = time.perf_counter()
        prepared = self.adapters.prepare(height_state.height, elite.decoded)
        preparation_time_s = time.perf_counter() - preparation_started
        selected = _StageCandidate(
            prepared=prepared,
            source=source,
            state=elite.state,
            decoded=elite.decoded,
            key=elite.key,
            breakdown=elite.breakdown,
            archive_categories=tagged.categories,
            anneal_stages=len(annealed),
            anneal_moves=len(annealed) * self.config.moves_per_stage,
            accepted_moves=sum(item.result.accepted_moves for item in annealed),
            anneal_seeds=tuple(item.restart.seed for item in annealed),
        )
        detailed_started = time.perf_counter()
        detailed = self.adapters.detailed_route(selected.prepared, allowance)
        detailed_route_time_s = time.perf_counter() - detailed_started
        spent = detailed.routing.expansions
        _check_spend(spent, allowance)
        return self._complete_routing_stage(
            height_state,
            selected,
            detailed,
            spent,
            observation=_RoutingObservation(
                restart=source.restart,
                stage_index=source.restart.stages - 1,
                backend=source.result.backend,
                continue_search=True,
            ),
            global_routes=0,
            global_overflow=None,
            global_skip_reason="quality-mode",
            preparation_time_s=preparation_time_s,
            global_route_time_s=0.0,
            detailed_route_time_s=detailed_route_time_s,
        )

    def _route_archive(
        self,
        height_state: _HeightState,
        candidates: Sequence[tuple[TaggedAnnealIncumbent, _AnnealedRestart]],
        annealed: Sequence[_AnnealedRestart],
        allowance: int,
        *,
        closure_allowance: int | None = None,
    ) -> tuple[int, bool]:
        """Proxy-score an archive without consuming its detailed closure work."""
        spent = 0
        preparation_time_s = 0.0
        global_route_time_s = 0.0
        anneal_stages = len(annealed)
        anneal_moves = anneal_stages * self.config.moves_per_stage
        accepted_moves = sum(item.result.accepted_moves for item in annealed)
        anneal_seeds = tuple(item.restart.seed for item in annealed)
        detailed_reserve = (
            min(
                allowance,
                max(
                    1,
                    _fraction_ceiling(
                        allowance,
                        self.config.final_reserve_fraction,
                    ),
                ),
            )
            if allowance
            else 0
        )
        proxy_left = 0 if closure_allowance is not None else allowance - detailed_reserve
        prepared_candidates: list[_StageCandidate[PreparedT]] = []
        global_candidates: list[_GlobalCandidate[PreparedT]] = []
        for index, (tagged, source) in enumerate(candidates):
            if proxy_left == 0 and prepared_candidates:
                break
            elite = tagged.incumbent
            preparation_started = time.perf_counter()
            prepared = self.adapters.prepare(height_state.height, elite.decoded)
            preparation_time_s += time.perf_counter() - preparation_started
            prepared_candidate = _StageCandidate(
                prepared=prepared,
                source=source,
                state=elite.state,
                decoded=elite.decoded,
                key=elite.key,
                breakdown=elite.breakdown,
                archive_categories=tagged.categories,
                anneal_stages=anneal_stages,
                anneal_moves=anneal_moves,
                accepted_moves=accepted_moves,
                anneal_seeds=anneal_seeds,
            )
            prepared_candidates.append(prepared_candidate)
            if proxy_left == 0:
                break

            remaining_candidates = len(candidates) - index
            proxy_allowance = (proxy_left + remaining_candidates - 1) // remaining_candidates
            global_started = time.perf_counter()
            global_result = self.adapters.global_route(
                prepared,
                height_state.feedback,
                proxy_allowance,
            )
            global_route_time_s += time.perf_counter() - global_started
            _check_spend(global_result.expansions, proxy_allowance)
            spent += global_result.expansions
            proxy_left -= global_result.expansions
            global_candidates.append(
                _GlobalCandidate(
                    prepared=prepared,
                    source=source,
                    state=elite.state,
                    decoded=elite.decoded,
                    key=elite.key,
                    breakdown=elite.breakdown,
                    archive_categories=tagged.categories,
                    anneal_stages=anneal_stages,
                    anneal_moves=anneal_moves,
                    accepted_moves=accepted_moves,
                    anneal_seeds=anneal_seeds,
                    result=global_result,
                )
            )
            if global_result.cancelled:
                break

        if global_candidates:
            chosen_global = min(global_candidates, key=_global_priority)
            selected: _StageCandidate[PreparedT] = chosen_global
            selected_result = chosen_global.result
            global_overflow = (
                selected_result.total_overflow
                if not selected_result.cancelled and not selected_result.exhausted_budget
                else None
            )
            global_skip_reason = None
        elif prepared_candidates:
            selected = prepared_candidates[0]
            global_overflow = None
            global_skip_reason = "proxy-budget"
        else:
            raise ValueError("archive routing requires at least one candidate")

        available_for_detail = allowance if closure_allowance is None else closure_allowance
        if available_for_detail < allowance:
            raise ValueError("detailed closure allowance cannot be smaller than proxy allowance")
        detailed_allowance = available_for_detail - spent
        detailed_started = time.perf_counter()
        detailed = self.adapters.detailed_route(selected.prepared, detailed_allowance)
        detailed_route_time_s = time.perf_counter() - detailed_started
        _check_spend(detailed.routing.expansions, detailed_allowance)
        spent += detailed.routing.expansions
        selected_source = selected.source
        if selected_source is None:
            raise ValueError("annealed global candidate must retain its restart source")
        return self._complete_routing_stage(
            height_state,
            selected,
            detailed,
            spent,
            observation=_RoutingObservation(
                restart=selected_source.restart,
                stage_index=selected_source.restart.stages - 1,
                backend=selected_source.result.backend,
                continue_search=True,
            ),
            global_routes=len(global_candidates),
            global_overflow=global_overflow,
            global_skip_reason=global_skip_reason,
            preparation_time_s=preparation_time_s,
            global_route_time_s=global_route_time_s,
            detailed_route_time_s=detailed_route_time_s,
        )

    def _complete_routing_stage(
        self,
        height_state: _HeightState,
        selected: _StageCandidate[PreparedT],
        detailed: DetailedStageResult,
        spent: int,
        observation: _RoutingObservation,
        *,
        global_routes: int,
        global_overflow: int | None,
        global_skip_reason: str | None,
        preparation_time_s: float,
        global_route_time_s: float,
        detailed_route_time_s: float,
    ) -> tuple[int, bool]:
        problem = height_state.problem
        starting_mode = height_state.objective_mode
        prior_height_exact = height_state.exact_key
        exact_key: tuple[int, int] | None = None
        pending_quality_exit = (
            height_state.pending_quality_exit if observation.continue_search else False
        )
        if observation.continue_search:
            height_state.pending_quality_exit = False
        validation_failures: tuple[str, ...] = ()
        validation_time_s = 0.0
        if detailed.routing.status is DetailedRouteStatus.ROUTED and detailed.placement is not None:
            validation_started = time.perf_counter()
            verdict = self.adapters.validate(detailed.placement)
            validation_time_s = time.perf_counter() - validation_started
            validation_failures = verdict.failed_checks
            if verdict.ok:
                exact_key = _exact_key(detailed.placement)
                if self._incumbent is None or exact_key < self._incumbent.exact_key:
                    self._incumbent = _ExactIncumbent(
                        exact_key=exact_key,
                        placement=detailed.placement,
                        candidate_key=selected.key,
                        breakdown=selected.breakdown,
                        archive_categories=selected.archive_categories,
                    )
                if height_state.exact_key is None or exact_key < height_state.exact_key:
                    height_state.exact_key = exact_key
        if not observation.continue_search:
            self._record_routing_observation(
                height_state,
                selected,
                detailed,
                spent,
                problem=problem,
                observation=observation,
                global_routes=global_routes,
                global_overflow=global_overflow,
                global_skip_reason=global_skip_reason,
                exact_key=exact_key,
                validation_failures=validation_failures,
                preparation_time_s=preparation_time_s,
                global_route_time_s=global_route_time_s,
                detailed_route_time_s=detailed_route_time_s,
                validation_time_s=validation_time_s,
                lns_size=0,
                variant_moves=0,
                split_count=0,
                merge_count=0,
                quality_entered=False,
                quality_exited=False,
            )
            return spent, False

        source = selected.source
        if source is None:
            raise ValueError("continuing routing stage must retain its annealed source")
        restart = observation.restart

        quality_entered = (
            starting_mode is ObjectiveMode.EXPLORATION
            and global_routes > 0
            and global_overflow == 0
            and exact_key is not None
        )
        quality_exited = pending_quality_exit or (
            starting_mode is ObjectiveMode.QUALITY and exact_key is None
        )
        if quality_entered:
            height_state.objective_mode = ObjectiveMode.QUALITY
            height_state.quality_restart = restart.restart
            height_state.quality_stagnation = 0
        elif starting_mode is ObjectiveMode.QUALITY:
            if quality_exited:
                height_state.objective_mode = ObjectiveMode.EXPLORATION
                height_state.quality_restart = None
                height_state.quality_stagnation = 0
            elif prior_height_exact is None or (
                exact_key is not None and exact_key < prior_height_exact
            ):
                height_state.quality_restart = restart.restart
                height_state.quality_stagnation = 0
            else:
                height_state.quality_restart = restart.restart
                height_state.quality_stagnation += 1
        elif pending_quality_exit:
            height_state.quality_restart = None
            height_state.quality_stagnation = 0

        annealed = source.result
        stage_start = source.stage_start
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
        if starting_mode is ObjectiveMode.EXPLORATION:
            height_state.feedback = update_feedback(
                decay_feedback(height_state.feedback), detailed.routing
            )
            if signature:
                restart.feedback_stagnation = (
                    restart.feedback_stagnation + 1 if signature == restart.failure_signature else 1
                )
            else:
                restart.feedback_stagnation = 0
            restart.failure_signature = signature
        else:
            restart.failure_signature = ()
            restart.feedback_stagnation = 0

        neighbourhood = frozenset[int]()
        next_anneal = AnnealState(
            pair=selected.state.pair,
            gaps=selected.state.gaps,
            base_seed=restart.seed,
            stage_index=annealed.final_state.stage_index,
            variant_indices=selected.state.variant_indices,
        )
        if starting_mode is ObjectiveMode.EXPLORATION and 0 < detailed.routing.failed_count <= 3:
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
        topology_changed = False
        if (
            starting_mode is ObjectiveMode.EXPLORATION
            and self.stage_boundary_transform is not None
            and signature
        ):
            transformed = self.stage_boundary_transform(
                height_state.height,
                problem,
                next_anneal,
                height_state.feedback,
                detailed.routing,
                restart.feedback_stagnation,
            )
            if transformed is not None:
                sibling_updates: list[tuple[_RestartState, StageBoundaryUpdate]] = []
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
                        if transformed.problem.size < problem.size:
                            transformed = None
                            break
                        raise ValueError(
                            "stage-boundary transform must rebuild every restart identically"
                        )
                    sibling_updates.append((other, sibling))
                if transformed is not None:
                    topology_changed = transformed.problem != problem
                    if self.stage_boundary_commit is not None:
                        self.stage_boundary_commit(
                            height_state.height,
                            transformed.problem,
                        )
                    for other, sibling in sibling_updates:
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
                    if topology_changed:
                        for candidate_restart in height_state.restarts:
                            candidate_restart.archive = ()
                        height_state.objective_mode = ObjectiveMode.EXPLORATION
                        height_state.quality_restart = None
                        height_state.pending_quality_exit = False
                        height_state.quality_stagnation = 0
                        height_state.narrowest_key = None

        restart.anneal = next_anneal
        height_state.stages += 1
        height_state.spent += spent
        if topology_changed:
            height_state.stranded = 1 << 60
            height_state.global_overflow = 1 << 60
            height_state.estimated_area = 1 << 60
        else:
            height_state.stranded = detailed.routing.failed_count
            if global_overflow is not None:
                height_state.global_overflow = global_overflow
            height_state.estimated_area = selected.decoded.width * height_state.height
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
        self._record_routing_observation(
            height_state,
            selected,
            detailed,
            spent,
            problem=problem,
            observation=observation,
            global_routes=global_routes,
            global_overflow=global_overflow,
            global_skip_reason=global_skip_reason,
            exact_key=exact_key,
            validation_failures=validation_failures,
            preparation_time_s=preparation_time_s,
            global_route_time_s=global_route_time_s,
            detailed_route_time_s=detailed_route_time_s,
            validation_time_s=validation_time_s,
            lns_size=len(neighbourhood),
            variant_moves=variant_moves,
            split_count=split_count,
            merge_count=merge_count,
            quality_entered=quality_entered,
            quality_exited=quality_exited,
        )
        return spent, False

    def _record_routing_observation(
        self,
        height_state: _HeightState,
        selected: _StageCandidate[PreparedT],
        detailed: DetailedStageResult,
        spent: int,
        *,
        problem: PlacementProblem,
        observation: _RoutingObservation,
        global_routes: int,
        global_overflow: int | None,
        global_skip_reason: str | None,
        exact_key: tuple[int, int] | None,
        validation_failures: tuple[str, ...],
        preparation_time_s: float,
        global_route_time_s: float,
        detailed_route_time_s: float,
        validation_time_s: float,
        lns_size: int,
        variant_moves: int,
        split_count: int,
        merge_count: int,
        quality_entered: bool,
        quality_exited: bool,
    ) -> None:
        selected_variant_ids = problem.selected_variant_ids(selected.state.variant_indices)
        selected_pose_yaws = (
            tuple(
                problem.variant(strip, variant).yaw
                for strip, variant in enumerate(selected.state.variant_indices)
            )
            if problem.variant_tables
            else ()
        )
        restart = observation.restart
        self._stage_stats.append(
            StageObservation(
                height=height_state.height,
                restart=restart.restart,
                stage_index=observation.stage_index,
                seed=restart.seed,
                accepted_moves=selected.accepted_moves,
                anneal_stages=selected.anneal_stages,
                anneal_moves=selected.anneal_moves,
                anneal_seeds=selected.anneal_seeds,
                backend=observation.backend,
                global_routes=global_routes,
                global_overflow=global_overflow,
                detailed_status=detailed.routing.status,
                stranded=detailed.routing.failed_count,
                expansions=spent,
                lns_size=lns_size,
                exact_key=exact_key,
                validation_failures=validation_failures,
                variant_moves=variant_moves,
                selected_instance_ids=problem.instance_ids,
                selected_variant_ids=selected_variant_ids,
                selected_pose_yaws=selected_pose_yaws,
                split_count=split_count,
                merge_count=merge_count,
                candidate_key=selected.key,
                breakdown=selected.breakdown,
                archive_categories=selected.archive_categories,
                preparation_time_s=preparation_time_s,
                global_route_time_s=global_route_time_s,
                detailed_route_time_s=detailed_route_time_s,
                validation_time_s=validation_time_s,
                objective_mode=height_state.objective_mode,
                global_skip_reason=global_skip_reason,
                quality_entered=quality_entered,
                quality_exited=quality_exited,
                stagnation_count=height_state.quality_stagnation,
            )
        )


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


def _validated_initial_states(
    problem_by_height: Mapping[int, PlacementProblem],
    initial_states: Mapping[int, AnnealState] | None,
) -> Mapping[int, AnnealState]:
    if initial_states is None:
        return MappingProxyType({})
    if not isinstance(initial_states, Mapping):
        raise ValueError("initial states must be an immutable height mapping")
    copied = dict(initial_states)
    for height, state in copied.items():
        if type(height) is not int or height not in problem_by_height:
            raise ValueError("initial state height must identify a scheduled problem")
        if not isinstance(state, AnnealState):
            raise ValueError("initial state mapping values must be annealing states")
        try:
            decoded = decode_state(problem_by_height[height], state)
        except ValueError as exc:
            raise ValueError("initial state must match its scheduled placement problem") from exc
        if decoded.used_height > height:
            raise ValueError("initial state must fit its scheduled placement problem")
    return MappingProxyType(copied)


def _new_height_state(
    order: int,
    height: int,
    problem: PlacementProblem,
    feedback_factory: Callable[[PlacementProblem], FeedbackState],
    config: SequenceSolverConfig,
    initial_state: AnnealState | None,
) -> _HeightState:
    if problem.outline_height != height:
        raise ValueError("height problem outline must match its scheduled height")
    height_seed = derive_stage_seed(config.seed, order)
    restarts: list[_RestartState] = []
    for restart in range(config.restarts_per_height):
        seed = derive_stage_seed(height_seed, restart)
        anneal = (
            AnnealState.initial(problem.size, seed)
            if initial_state is None
            else replace(initial_state, base_seed=seed, stage_index=0)
        )
        restarts.append(
            _RestartState(
                restart=restart,
                seed=seed,
                anneal=anneal,
            )
        )
    return _HeightState(
        order=order,
        height=height,
        problem=problem,
        feedback=feedback_factory(problem),
        restarts=restarts,
        routing_seed=initial_state,
    )


def _legal_quality_candidate(
    archive: Sequence[TaggedAnnealIncumbent],
) -> AnnealIncumbent | None:
    legal = tuple(
        tagged.incumbent
        for tagged in archive
        if tagged.incumbent.breakdown.hard_outline_overflow == 0
    )
    return min(legal, key=quality_archive_key, default=None)


def _height_priority(
    height: _HeightState,
) -> tuple[
    int,
    tuple[int, int],
    int,
    int,
    int,
    QualityArchiveKey | tuple[()],
    int,
    int,
]:
    return (
        0 if height.exact_key is not None else 1,
        height.exact_key or (0, 0),
        height.stranded,
        height.global_overflow,
        0 if height.narrowest_key is not None else 1,
        height.narrowest_key or (),
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
                port_dock_plan=variant.port_dock_plan,
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


def _balanced_compact_seed_height(problem: PlacementProblem) -> int:
    """Choose a width-major near-square height from authoritative feasible boxes."""
    choices: list[tuple[tuple[int, int], ...]] = []
    if problem.variant_tables:
        selection = [0] * problem.size
        for strip, variants in enumerate(problem.variant_tables):
            sizes: list[tuple[int, int]] = []
            for variant in range(len(variants)):
                selection[strip] = variant
                sizes.append(problem.selected_sizes(tuple(selection))[strip])
            selection[strip] = 0
            choices.append(tuple(sizes))
    else:
        choices.extend((size,) for size in problem.sizes)

    feasible_area = sum(
        min(width * height for width, height in strip_choices) for strip_choices in choices
    )
    area = max(problem.area_lower_bound, feasible_area, 1)
    balanced_width = math.isqrt(area)
    if balanced_width * balanced_width < area:
        balanced_width += 1
    balanced_height = area // balanced_width
    minimum_height = max(
        (min(height for _width, height in strip_choices) for strip_choices in choices),
        default=1,
    )
    return max(minimum_height, balanced_height)


def _variant_direct_eligibility(
    spec: BuildSpec,
    strips: list[Strip],
    problem: PlacementProblem,
) -> tuple[VariantDirectInsertTarget, ...]:
    """Enumerate only endpoint-variant pairs production can directly attach."""
    defaults = (0,) * problem.size
    baseline = _selected_direct_targets(spec, strips, problem, defaults)
    if not baseline:
        return ()

    variant_counts = (
        tuple(len(table) for table in problem.variant_tables)
        if problem.variant_tables
        else (1,) * problem.size
    )
    eligible: list[VariantDirectInsertTarget] = []
    for candidate in baseline:
        for producer_variant in range(variant_counts[candidate.producer]):
            for consumer_variant in range(variant_counts[candidate.consumer]):
                selection = list(defaults)
                selection[candidate.producer] = producer_variant
                selection[candidate.consumer] = consumer_variant
                selected = {
                    target.key: target
                    for target in _selected_direct_targets(
                        spec,
                        strips,
                        problem,
                        tuple(selection),
                    )
                }
                target = selected.get(candidate.key)
                if target is not None:
                    eligible.append(
                        VariantDirectInsertTarget(
                            producer_variant,
                            consumer_variant,
                            target,
                        )
                    )
    return tuple(eligible)


def _placement_nets(
    strips: Sequence[Strip],
) -> tuple[tuple[tuple[int, int], LogicalNetId], ...]:
    """Return every exact logical edge with its current physical endpoints."""
    by_group: dict[str, list[int]] = {}
    for index, strip in enumerate(strips):
        by_group.setdefault(strip.group_key, []).append(index)
    nets = {
        (
            (source, destination),
            LogicalNetId(
                strip.family_id,
                strips[destination].family_id,
                item,
                NetRole.INTERNAL,
            ),
        )
        for source, strip in enumerate(strips)
        for item, destination_groups in strip.out_lanes
        for destination_group in _dests(destination_groups)
        for destination in by_group.get(destination_group, ())
    }
    return tuple(
        sorted(
            nets,
            key=lambda entry: (
                entry[0],
                entry[1].item,
                entry[1].role.value,
            ),
        )
    )


def _rebuild_stage_problem_nets(
    problem: PlacementProblem,
    nets: tuple[tuple[tuple[int, int], LogicalNetId], ...],
) -> PlacementProblem:
    """Rebind sorted physical nets and exact logical ids as one value."""
    ordered = tuple(
        sorted(
            nets,
            key=lambda entry: (
                entry[0],
                entry[1].item,
                entry[1].role.value,
            ),
        )
    )
    return replace(
        problem,
        nets=tuple(endpoints for endpoints, _logical in ordered),
        logical_net_ids=tuple(logical for _endpoints, logical in ordered),
    )


def _pose_stage_boundary_update(
    problem: PlacementProblem,
    state: AnnealState,
    result: DetailedRouteResult,
    *,
    stagnation: int,
    family_by_id: dict[StripFamilyId, StripFamily],
) -> StageBoundaryUpdate | None:
    """Apply one deterministic legal topology change after a completed stage."""
    if not problem.instance_ids:
        return None

    target = select_split_candidate(
        result,
        problem.instance_ids,
        stagnation=stagnation,
        split_after=2,
    )
    if target is not None:
        family = family_by_id[problem.instance_ids[target].family_id]
        return split_stage_boundary(
            problem,
            state,
            family,
            target,
            right_variant_offset=1 if len(family.variants) > 1 else 0,
        )

    implicated = geometric_failure_instances(result, problem.size)
    for left_strip in range(problem.size - 1):
        right_strip = left_strip + 1
        if left_strip in implicated or right_strip in implicated:
            continue
        left_id = problem.instance_ids[left_strip]
        right_id = problem.instance_ids[right_strip]
        if (
            left_id.family_id != right_id.family_id
            or left_id.machine_start + left_id.machine_count != right_id.machine_start
        ):
            continue
        merge_family = family_by_id.get(left_id.family_id)
        if merge_family is None:
            continue
        merged = merge_stage_boundary(
            problem,
            state,
            merge_family,
            left_strip,
            right_strip,
        )
        if merged is not None:
            return merged
    return None


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
    compact_seed_attempt: int | None = None
    compact_seed_base_seed: int | None = None
    compact_seed_height: int | None = None
    compact_seed_result: CompactSeedResult | None = None
    compact_seed_wall_time_s: float = 0.0


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
    belt_vertical_construction: bool = True,
    absolute_deadline: float | None = None,
    compact_seed_attempt: int | None = None,
    compact_seed_base_seed: int | None = None,
    compact_seed_config: CompactSeedConfig | None = None,
) -> _ProductionRun:
    started = time.monotonic()
    ceiling = max(time_budget_s, RETRY_BUDGET_S)
    deadline = started + ceiling if absolute_deadline is None else absolute_deadline

    def deadline_reached() -> bool:
        return time.monotonic() >= deadline

    telemetry = _ProductionTelemetry()
    if compact_seed_attempt is not None and (
        type(compact_seed_attempt) is not int or compact_seed_attempt < 0
    ):
        raise ValueError("compact seed attempt must be a non-negative integer or None")
    if compact_seed_base_seed is not None and type(compact_seed_base_seed) is not int:
        raise ValueError("compact seed base seed must be an integer or None")
    chosen_compact_base_seed = (
        config.seed if compact_seed_base_seed is None else compact_seed_base_seed
    )
    if compact_seed_config is None:
        chosen_compact_config = CompactSeedConfig()
    elif type(compact_seed_config) is CompactSeedConfig:
        chosen_compact_config = compact_seed_config
    else:
        raise ValueError("compact seed config must be exactly CompactSeedConfig")
    chosen_compact_config = _budgeted_compact_seed_config(
        time_budget_s,
        chosen_compact_config,
    )
    initial_states: dict[int, AnnealState] = {}

    planning_started = time.monotonic()
    try:
        planned_strip_len = strip_len
        try:
            strips = plan_strips(spec, strip_len=planned_strip_len)
        except (KeyError, ValueError) as exc:
            try:
                planned_strip_len = max(1, spec.machine_count)
                strips = plan_strips(spec, strip_len=planned_strip_len)
            except KeyError, ValueError:
                raise NoValidLayout(
                    f"the spec cannot be split into strips: {exc}",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                ) from exc
        strips, planned_strip_len = _coarsen_saturated_strip_plan(
            spec,
            strips,
            strip_len=planned_strip_len,
        )
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
        placement_nets = _placement_nets(strips)
        nets = tuple(endpoints for endpoints, _logical in placement_nets)
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
        coarse_heights = tuple(sorted(seeds, key=lambda height: (seeds[height].width, height)))
        neighbor_heights: list[int] = []
        for height in coarse_heights:
            neighbor = height + 2
            if neighbor in seeds:
                continue
            seeds[neighbor] = _greedy_pack(strips, neighbor)
            neighbor_heights.append(neighbor)
        protected_followup_heights = tuple(neighbor_heights)
        heights = coarse_heights + protected_followup_heights
        problems = {
            height: PlacementProblem(
                sizes=sizes,
                nets=nets,
                outline_height=height,
                area_lower_bound=area_lower_bound,
                instance_ids=instance_ids,
                variant_tables=variant_tables,
                logical_net_ids=tuple(logical for _endpoints, logical in placement_nets),
            )
            for height in heights
        }
        if compact_seed_attempt is not None:
            template_problem = problems[heights[0]]
            compact_height = _balanced_compact_seed_height(template_problem)
            telemetry.compact_seed_base_seed = chosen_compact_base_seed
            telemetry.compact_seed_height = compact_height
            if compact_height not in seeds:
                seeds[compact_height] = _greedy_pack(strips, compact_height)
            if compact_height not in problems:
                problems[compact_height] = replace(
                    template_problem,
                    outline_height=compact_height,
                )
            heights = (compact_height,) + tuple(
                height for height in heights if height != compact_height
            )
            if compact_height not in protected_followup_heights:
                protected_followup_heights += (compact_height,)
            large_variant_seed = (
                bool(problems[compact_height].variant_tables)
                and problems[compact_height].size >= _COMPACT_LARGE_VARIANT_SIZE
            )
            effective_compact_attempt = compact_seed_attempt
            telemetry.compact_seed_attempt = effective_compact_attempt

            compact_started = time.monotonic()
            compact_deadline = min(
                deadline,
                compact_started
                + ceiling
                * _COMPACT_SEED_WALL_SHARE.numerator
                / _COMPACT_SEED_WALL_SHARE.denominator,
            )
            try:
                direct_eligibility = (
                    _variant_direct_eligibility(
                        spec,
                        strips,
                        problems[compact_height],
                    )
                    if ceiling >= _COMPACT_SEED_DIRECT_MIN_BUDGET_S and not deadline_reached()
                    else ()
                )
                seed_config = (
                    replace(
                        chosen_compact_config,
                        max_deterministic_time=min(
                            chosen_compact_config.max_deterministic_time,
                            _COMPACT_LARGE_VARIANT_DETERMINISTIC_CAP,
                        ),
                    )
                    if large_variant_seed
                    else chosen_compact_config
                )
                compact_result = solve_compact_seed(
                    problems[compact_height],
                    base_seed=chosen_compact_base_seed,
                    attempt=effective_compact_attempt,
                    config=seed_config,
                    direct_eligibility=direct_eligibility,
                    absolute_deadline=compact_deadline,
                    cancelled=deadline_reached,
                )
            except Exception as exc:
                compact_result = CompactSeedResult(
                    CompactSeedStatus.INVALID,
                    None,
                    CompactSeedDiagnostics(
                        solver_seed=0,
                        status_name="INVALID",
                        width_weight=1,
                        secondary_upper_bound=0,
                        validation_error=f"{type(exc).__name__}: {exc}",
                    ),
                )
            finally:
                telemetry.compact_seed_wall_time_s = time.monotonic() - compact_started
            if compact_result.state is not None:
                try:
                    validated = _validated_initial_states(
                        {compact_height: problems[compact_height]},
                        {compact_height: compact_result.state},
                    )
                except ValueError as exc:
                    compact_result = CompactSeedResult(
                        CompactSeedStatus.INVALID,
                        None,
                        replace(
                            compact_result.diagnostics,
                            status_name="INVALID",
                            validation_error=f"{type(exc).__name__}: {exc}",
                        ),
                    )
                else:
                    initial_states.update(validated)
            telemetry.compact_seed_result = compact_result
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
                ramped=not belt_vertical_construction,
            )
        except (_Unpowerable, _Unseatable) as exc:
            return _ProductionCandidate(
                height=height,
                problem=problem,
                decoded=aligned,
                pack=pack,
                prepared=None,
                preparation_error=("unseatable" if isinstance(exc, _Unseatable) else "unpowerable"),
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
        result = _route_detailed_candidate(
            spec,
            list(candidate.selected_strips) if candidate.selected_strips else strips,
            candidate.prepared,
            power=power,
            deadline=deadline,
            allowance=allowance,
        )
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
        if deadline_reached():
            return ValidationVerdict(False, ("deadline",))
        report = validate.certify(placement, spec, expect_power=power)
        failures = tuple(sorted({finding.check for finding in report.errors}))
        return ValidationVerdict(not failures, failures)

    family_by_id = {family.family_id: family for family in generate_strip_families(spec)}
    telemetry.pose_feasibility_rejects = sum(
        4 - len({variant.yaw for variant in family.variants}) for family in family_by_id.values()
    )

    def transform_stage(
        height: int,
        problem: PlacementProblem,
        state: AnnealState,
        _feedback: FeedbackState,
        result: DetailedRouteResult,
        stagnation: int,
    ) -> StageBoundaryUpdate | None:
        transformed = _pose_stage_boundary_update(
            problem,
            state,
            result,
            stagnation=stagnation,
            family_by_id=family_by_id,
        )
        if transformed is None:
            return None
        selected = _selected_strips(
            strips,
            transformed.problem,
            transformed.state.variant_indices,
        )
        rebuilt = _rebuild_stage_problem_nets(
            transformed.problem,
            _placement_nets(selected),
        )
        return StageBoundaryUpdate(rebuilt, transformed.state)

    def commit_stage(height: int, problem: PlacementProblem) -> None:
        problems[height] = problem
        selected_cache.clear()
        direct_cache.clear()

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
        borrow_first_discovery=compact_seed_attempt is not None,
        protected_followup_heights=protected_followup_heights,
        config=config,
        deadline_reached=deadline_reached,
        initial_states=initial_states,
        direct_targets=direct_targets,
        direct_targets_for_state=direct_targets_for_state,
        stage_boundary_transform=transform_stage,
        stage_boundary_commit=commit_stage,
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
    """Closed-loop sequence-pair layout backend."""

    name = "sequence-pair"

    def __init__(
        self,
        *,
        power: bool = False,
        belt_vertical_construction: bool = True,
        strip_len: int = 6,
        config: SequenceSolverConfig | None = None,
        solver_factory: _SolverFactory | None = None,
        compact_seed_config: CompactSeedConfig | None = None,
        islands: int = 1,
    ) -> None:
        if type(power) is not bool:
            raise ValueError("power mode must be a bool")
        if type(strip_len) is not int or strip_len <= 0:
            raise ValueError("strip length must be a positive integer")
        if type(islands) is not int or not 1 <= islands <= _MAX_SEQUENCE_ISLANDS:
            raise ValueError(f"islands must be an integer from 1 to {_MAX_SEQUENCE_ISLANDS}")
        if solver_factory is not None and islands != 1:
            raise ValueError("solver factory requires exactly one island")
        if compact_seed_config is not None and type(compact_seed_config) is not CompactSeedConfig:
            raise ValueError("compact seed config must be exactly CompactSeedConfig")
        self._solver_factory = solver_factory
        self.power = power
        self.ramped = not belt_vertical_construction
        self.strip_len = strip_len
        self.config = config or SequenceSolverConfig()
        self.compact_seed_config = compact_seed_config or CompactSeedConfig()
        self.islands = islands

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

        if self.islands > 1:
            from flab2bp.layout.sequence_islands import run_sequence_islands

            return run_sequence_islands(
                spec,
                time_budget_s=time_budget_s,
                power=self.power,
                belt_vertical_construction=not self.ramped,
                strip_len=self.strip_len,
                config=self.config,
                compact_seed_config=self.compact_seed_config,
                islands=self.islands,
            )

        run = _production_run(
            spec,
            time_budget_s=time_budget_s,
            power=self.power,
            belt_vertical_construction=not self.ramped,
            strip_len=self.strip_len,
            config=self.config,
            compact_seed_attempt=_serial_compact_seed_attempt(
                spec.machine_count,
                len(spec.spray_lanes),
            ),
            compact_seed_base_seed=self.config.seed,
            compact_seed_config=_budgeted_compact_seed_config(
                time_budget_s,
                self.compact_seed_config,
            ),
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
    preparation_time_s = sum(stage.preparation_time_s for stage in result.stages)
    global_route_time_s = sum(stage.global_route_time_s for stage in result.stages)
    detailed_route_time_s = sum(stage.detailed_route_time_s for stage in result.stages)
    validation_time_s = sum(stage.validation_time_s for stage in result.stages)
    adapter_time_s = (
        telemetry.planning_time_s
        + preparation_time_s
        + global_route_time_s
        + detailed_route_time_s
        + validation_time_s
    )
    stage_count = len(result.stages)
    anneal_stage_count = sum(stage.anneal_stages for stage in result.stages)
    anneal_seeds = {seed for stage in result.stages for seed in stage.anneal_seeds}
    lns_sizes = tuple(stage.lns_size for stage in result.stages)
    belt_tiles = _exact_key(placement)[1]
    breakdown = result.exact_breakdown
    exact_stage = next(
        (
            stage
            for stage in result.stages
            if stage.exact_key == result.exact_key
            and stage.candidate_key == result.exact_candidate_key
        ),
        None,
    )
    pose_yaws = exact_stage.selected_pose_yaws if exact_stage is not None else ()
    skipped_global_stages = tuple(
        stage for stage in result.stages if stage.global_skip_reason is not None
    )
    quality_stages = tuple(
        stage for stage in result.stages if stage.global_skip_reason == "quality-mode"
    )
    compact_closures = tuple(
        stage for stage in result.stages if stage.global_skip_reason == "compact-seed"
    )
    pose_counts = {
        yaw: sum(selected == yaw for selected in pose_yaws) for yaw in (0.0, 90.0, 180.0, 270.0)
    }
    stats: dict[str, object] = dict(placement.stats)
    observed_backends = {stage.backend for stage in result.stages}
    accelerator = "mixed" if len(observed_backends) > 1 else next(iter(observed_backends), "python")
    stats.update(
        {
            "backend": "sequence-pair",
            "accelerator": accelerator,
            "seed": config.seed,
            "seeds": float(len(anneal_seeds)),
            "heights": float(len(run.heights)),
            "restarts": float(len(run.heights) * config.restarts_per_height),
            "stages": float(stage_count),
            "anneal_stages": float(anneal_stage_count),
            "moves": float(sum(stage.anneal_moves for stage in result.stages)),
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
            "feedback_decays": float(sum(stage.global_routes > 0 for stage in result.stages)),
            "archive_categories": [category.value for category in result.exact_archive_categories],
            "archive_category": result.exact_archive_categories[0].value,
            "objective_mode": (
                exact_stage.objective_mode.value
                if exact_stage is not None
                else ObjectiveMode.EXPLORATION.value
            ),
            "global_skip_reason": (
                exact_stage.global_skip_reason
                if exact_stage is not None and exact_stage.global_skip_reason is not None
                else "none"
            ),
            "quality_stages": float(len(quality_stages)),
            "quality_entries": float(sum(stage.quality_entered for stage in result.stages)),
            "quality_exits": float(sum(stage.quality_exited for stage in result.stages)),
            "global_skips": float(len(skipped_global_stages)),
            "max_quality_stagnation": float(
                max((stage.stagnation_count for stage in result.stages), default=0)
            ),
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
            "preparation_time_s": preparation_time_s,
            "global_route_time_s": global_route_time_s,
            "detailed_route_time_s": detailed_route_time_s,
            "validation_time_s": validation_time_s,
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
            "pack_width": float(breakdown.width),
            "target_height": float(breakdown.outline_height),
            "used_height": float(breakdown.used_height),
            "box_area": float(breakdown.box_area),
            "gap_area": float(breakdown.gap_area),
            "weighted_hpwl": breakdown.weighted_hpwl,
            "history_cost": breakdown.history_cost,
            "missed_direct_inserts": float(breakdown.missed_direct_inserts),
            "hard_outline_overflow": float(breakdown.hard_outline_overflow),
            "search_energy": breakdown.energy.scalar,
            "power": float(power),
            "termination": result.termination,
            "termination_cause": result.termination,
            "validation_clean": 1.0,
            "validation_status": "clean",
        }
    )
    compact_result = telemetry.compact_seed_result
    compact_height = telemetry.compact_seed_height
    compact_attempt = telemetry.compact_seed_attempt
    compact_base_seed = telemetry.compact_seed_base_seed
    if compact_result is not None and compact_height is not None and compact_attempt is not None:
        diagnostics = compact_result.diagnostics
        compact_closure = compact_closures[0] if compact_closures else None
        stats.update(
            {
                "compact_seed_attempt": float(compact_attempt),
                "compact_seed_base_seed": (
                    compact_base_seed if compact_base_seed is not None else config.seed
                ),
                "compact_seed_status": compact_result.status.value,
                "compact_seed_height": float(compact_height),
                "compact_seed_solved_width": float(
                    diagnostics.solved_width if diagnostics.solved_width is not None else -1
                ),
                "compact_seed_decoded_width": float(
                    diagnostics.decoded_width if diagnostics.decoded_width is not None else -1
                ),
                "compact_seed_decoded_height": float(
                    diagnostics.decoded_height if diagnostics.decoded_height is not None else -1
                ),
                "compact_seed_deterministic_time_s": diagnostics.deterministic_time,
                "compact_seed_wall_time_s": telemetry.compact_seed_wall_time_s,
                "compact_seed_closures": float(len(compact_closures)),
                "compact_seed_closure_status": (
                    compact_closure.detailed_status.value
                    if compact_closure is not None
                    else "not-run"
                ),
                "compact_seed_closure_backend": (
                    compact_closure.backend if compact_closure is not None else "not-run"
                ),
                "compact_seed_closure_exact": float(
                    compact_closure is not None and compact_closure.exact_key is not None
                ),
            }
        )
    # Placement predates string-valued audit dimensions.  Keep the public
    # runtime contract required by the audit backend without widening the shared
    # production type in this audit-only task.
    return replace(placement, stats=cast(dict[str, float], stats))
