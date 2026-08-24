"""Deterministic staged orchestration for sequence-pair routing search.

This module owns scheduling and accounting only.  Task 11 binds the production
preparer, routers, and validator; keeping those adapters injected here makes a
proxy result incapable of becoming an exact incumbent by construction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Protocol

from flab2bp.layout.base import NoValidLayout, Placement
from flab2bp.layout.global_router import GlobalRouteResult
from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    decay_feedback,
    feedback_cost_context,
    select_lns_neighbourhood,
    update_feedback,
)
from flab2bp.layout.sequence_pair import (
    AnnealConfig,
    AnnealState,
    DecodedPlacement,
    PlacementProblem,
    anneal_stage,
    decode_sequence_pair,
    derive_stage_seed,
    repair_neighbourhood,
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

    def configure(
        self, heights: tuple[int, ...], reserve_fraction: Fraction
    ) -> None:
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
            spent = self._run_stage(height_state, restart, allowance)
            if discovery is not None:
                self.budget.settle_discovery(height_state.height, spent)
            else:
                self.budget.settle_shared(spent)

        if self._incumbent is None:
            reason = {
                "deadline": "deadline exhausted before finding an exact layout",
                "budget": "expansion budget exhausted before finding an exact layout",
                "candidates": "all scheduled candidates were exhausted",
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
    ) -> int:
        problem = height_state.problem
        current_decoded = decode_sequence_pair(
            restart.anneal.pair,
            restart.anneal.gaps,
            problem.sizes,
            outline_height=problem.outline_height,
        )
        context = feedback_cost_context(height_state.feedback, problem, current_decoded)
        annealed = anneal_stage(
            problem,
            restart.anneal,
            AnnealConfig(
                moves_per_stage=self.config.moves_per_stage,
                elite_count=max(self.config.global_elites, 1),
            ),
            context,
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
        detailed = self.adapters.detailed_route(selected.prepared, allowance - spent)
        _check_spend(detailed.routing.expansions, allowance - spent)
        spent += detailed.routing.expansions

        exact_key: tuple[int, int] | None = None
        validation_failures: tuple[str, ...] = ()
        if (
            detailed.routing.status is DetailedRouteStatus.ROUTED
            and detailed.placement is not None
        ):
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
        neighbourhood = frozenset[int]()
        next_anneal = annealed.final_state
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
                )
                next_anneal = AnnealState(
                    pair=repaired.pair,
                    gaps=repaired.gaps,
                    base_seed=restart.seed,
                    stage_index=annealed.final_state.stage_index,
                )

        restart.anneal = next_anneal
        restart.stages += 1
        height_state.stages += 1
        height_state.spent += spent
        height_state.stranded = detailed.routing.failed_count
        height_state.global_overflow = selected.result.total_overflow
        height_state.estimated_area = selected.decoded.width * height_state.height
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
            )
        )
        return spent


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
    width = sum(width for width, _height in problem.sizes) + 4 * problem.size
    return FeedbackState.empty((width, problem.outline_height))


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
) -> tuple[int, int, int, int, int, int, tuple[int, ...], tuple[int, ...]]:
    result = candidate.result
    return (
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
    """Audit-only layout surface; production adapters are bound in Task 11."""

    def __init__(
        self,
        *,
        solver_factory: _SolverFactory,
        power: bool = False,
        strip_len: int = 6,
        config: SequenceSolverConfig | None = None,
    ) -> None:
        if type(power) is not bool:
            raise ValueError("power mode must be a bool")
        if type(strip_len) is not int or strip_len <= 0:
            raise ValueError("strip length must be a positive integer")
        self._solver_factory = solver_factory
        self.power = power
        self.strip_len = strip_len
        self.config = config or SequenceSolverConfig()

    def lay_out(self, spec: BuildSpec, *, time_budget_s: float) -> Placement:
        """Run the injected audit backend without registering it for production."""
        if time_budget_s <= 0:
            raise ValueError("time budget must be positive")
        solver = self._solver_factory(
            spec,
            time_budget_s=time_budget_s,
            power=self.power,
            strip_len=self.strip_len,
            config=self.config,
        )
        return solver.search().placement
