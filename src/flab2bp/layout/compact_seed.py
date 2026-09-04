"""Deterministic routing-aware CP-SAT seeds for sequence-pair search.

The CP coordinates in this module exist only to construct a compact sequence pair.
The returned zero-gap :class:`AnnealState` is decoded and validated again through the
production sequence-pair representation; no CP placement is exposed as a layout.
"""

from __future__ import annotations

import contextlib
import itertools
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from ortools.sat.python import cp_model

from flab2bp.dsp import catalog
from flab2bp.layout.sequence_pair import (
    AnnealState,
    DecodedPlacement,
    DirectInsertTarget,
    GapProfile,
    PlacementProblem,
    SequencePair,
    decode_state,
    derive_stage_seed,
)
from flab2bp.layout.strip_variants import StripVariant, StripVariantId

_HPWL_WEIGHT = 1
_MISSED_DIRECT_WEIGHT = 4

_CP_INT_MAX = (1 << 63) - 1
_RANDOM_SEED_MODULUS = (1 << 31) - 1
_DEADLINE_SAFETY_SECONDS = 0.01
_MAX_DETERMINISTIC_TIME = 3_600.0


class CompactSeedStatus(StrEnum):
    """Honest terminal status for one compact-seed attempt."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class CompactSeedConfig:
    """Bounded deterministic work allowed for one single-worker CP-SAT solve."""

    max_deterministic_time: float = 5.0

    def __post_init__(self) -> None:
        if (
            type(self.max_deterministic_time) is not float
            or not math.isfinite(self.max_deterministic_time)
            or not 0.0 < self.max_deterministic_time <= _MAX_DETERMINISTIC_TIME
        ):
            raise ValueError("maximum deterministic time must be a finite float in (0.0, 3600.0]")


@dataclass(frozen=True, slots=True)
class VariantDirectInsertTarget:
    """One production-authoritative direct target and its eligible variant pair."""

    producer_variant: int
    consumer_variant: int
    target: DirectInsertTarget

    def __post_init__(self) -> None:
        if type(self.producer_variant) is not int or self.producer_variant < 0:
            raise ValueError("producer variant must be a non-negative integer")
        if type(self.consumer_variant) is not int or self.consumer_variant < 0:
            raise ValueError("consumer variant must be a non-negative integer")
        if not isinstance(self.target, DirectInsertTarget):
            raise ValueError("variant direct eligibility must carry a direct-insert target")


@dataclass(frozen=True, slots=True)
class CompactSeedDiagnostics:
    """Immutable solver observations; CP geometry remains explicitly advisory."""

    solver_seed: int
    status_name: str
    width_weight: int
    secondary_upper_bound: int
    objective_value: int | None = None
    best_objective_bound: int | None = None
    branches: int = 0
    conflicts: int = 0
    deterministic_time: float = 0.0
    solved_x: tuple[int, ...] | None = None
    solved_y: tuple[int, ...] | None = None
    solved_sizes: tuple[tuple[int, int], ...] | None = None
    solved_width: int | None = None
    decoded_width: int | None = None
    decoded_height: int | None = None
    positive_ranks: tuple[int, ...] | None = None
    negative_ranks: tuple[int, ...] | None = None
    selected_variant_ids: tuple[StripVariantId, ...] = ()
    selected_port_offsets: tuple[tuple[int, int, int, int], ...] = ()
    cp_direct_keys: frozenset[tuple[int, int]] = frozenset()
    decoded_direct_keys: frozenset[tuple[int, int]] = frozenset()
    validation_error: str | None = None


@dataclass(frozen=True, slots=True)
class CompactSeedResult:
    """One validated immutable seed, or an explicit status with no seed."""

    status: CompactSeedStatus
    state: AnnealState | None
    diagnostics: CompactSeedDiagnostics

    def __post_init__(self) -> None:
        has_incumbent = self.status in (CompactSeedStatus.OPTIMAL, CompactSeedStatus.FEASIBLE)
        if has_incumbent != (self.state is not None):
            raise ValueError("compact seed status and incumbent presence disagree")


type PairwiseRelation = tuple[bool, bool, bool, bool]
type PairwiseRelationEntry = tuple[tuple[int, int], PairwiseRelation]


def _solved_pairwise_relation(
    solver: cp_model.CpSolver,
    literals: tuple[cp_model.IntVar, ...],
) -> PairwiseRelation:
    if len(literals) != 4:
        raise ValueError("pairwise relation variables must have cardinality four")
    return (
        bool(solver.value(literals[0])),
        bool(solver.value(literals[1])),
        bool(solver.value(literals[2])),
        bool(solver.value(literals[3])),
    )


@dataclass(frozen=True, slots=True)
class PairwiseRelationSignature:
    """Complete pairwise left/right/below/above identity for one exact packing."""

    entries: tuple[PairwiseRelationEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise ValueError("pairwise relation entries must be an immutable tuple")
        prior: tuple[int, int] | None = None
        for pair, relation in self.entries:
            if (
                not isinstance(pair, tuple)
                or len(pair) != 2
                or any(type(index) is not int or index < 0 for index in pair)
                or pair[0] >= pair[1]
            ):
                raise ValueError("pairwise relations require increasing non-negative pairs")
            if prior is not None and pair <= prior:
                raise ValueError("pairwise relation pairs must be strictly ordered")
            if (
                not isinstance(relation, tuple)
                or len(relation) != 4
                or any(type(value) is not bool for value in relation)
                or not any(relation)
            ):
                raise ValueError("pairwise relations require four booleans with one separation")
            prior = pair


@dataclass(frozen=True, slots=True)
class CompactTopologyBeamConfig:
    """Deterministic work and cardinality bounds for exact CP topology candidates."""

    max_candidates: int = 2
    max_deterministic_time: float = 0.2
    refine_width_first: bool = False

    def __post_init__(self) -> None:
        if type(self.max_candidates) is not int or self.max_candidates <= 0:
            raise ValueError("maximum topology candidates must be a positive integer")
        if (
            type(self.max_deterministic_time) is not float
            or not math.isfinite(self.max_deterministic_time)
            or not 0.0 < self.max_deterministic_time <= _MAX_DETERMINISTIC_TIME
        ):
            raise ValueError("topology deterministic time must be a finite float in (0.0, 3600.0]")
        if type(self.refine_width_first) is not bool:
            raise ValueError("topology refinement flag must be exactly boolean")


@dataclass(frozen=True, slots=True)
class CompactTopologyCandidate:
    """One exact CP packing retained without sequence-pair re-encoding."""

    topology_index: int
    status: CompactSeedStatus
    x: tuple[int, ...]
    y: tuple[int, ...]
    width: int
    used_height: int
    variant_indices: tuple[int, ...]
    signature: PairwiseRelationSignature
    deterministic_time: float


@dataclass(frozen=True, slots=True)
class _TopologyBeamVariables:
    x: tuple[cp_model.IntVar, ...]
    y: tuple[cp_model.IntVar, ...]
    outline_width: cp_model.IntVar
    relations: tuple[tuple[cp_model.IntVar, ...], ...]


class CompactTopologyBeam:
    """Enumerate deterministic fixed-height packings through typed relation no-goods."""

    def __init__(
        self,
        problem: PlacementProblem,
        *,
        variant_indices: tuple[int, ...],
        width_bound: int,
        base_seed: int,
        coordinate_hint: DecodedPlacement | None,
        direct_targets: tuple[DirectInsertTarget, ...] = (),
        config: CompactTopologyBeamConfig | None = None,
    ) -> None:
        if not isinstance(problem, PlacementProblem):
            raise ValueError("topology beam problem must be a PlacementProblem")
        if type(base_seed) is not int:
            raise ValueError("topology beam seed must be an integer")
        if type(width_bound) is not int or width_bound <= 0:
            raise ValueError("topology width bound must be a positive integer")
        problem._validate_variant_indices(variant_indices)
        sizes = problem.selected_sizes(variant_indices)
        if any(width > width_bound for width, _height in sizes):
            raise ValueError("topology width bound must hold every selected rectangle")
        if coordinate_hint is not None:
            if not isinstance(coordinate_hint, DecodedPlacement):
                raise ValueError("topology coordinate hint must be a decoded placement")
            if len(coordinate_hint.x) != problem.size:
                raise ValueError("topology coordinate hint cardinality must match the problem")
            if (
                coordinate_hint.variant_indices
                and coordinate_hint.variant_indices != variant_indices
            ):
                raise ValueError("topology coordinate hint variants must match the problem")
        if not isinstance(direct_targets, tuple):
            raise ValueError("topology direct targets must be an immutable tuple")
        if any(not isinstance(target, DirectInsertTarget) for target in direct_targets):
            raise ValueError("topology direct targets must contain DirectInsertTarget values")
        if any(
            target.producer >= problem.size or target.consumer >= problem.size
            for target in direct_targets
        ):
            raise ValueError("topology direct targets must identify problem strips")
        if len({target.key for target in direct_targets}) != len(direct_targets):
            raise ValueError("topology direct target keys must be unique")
        if config is None:
            chosen_config = CompactTopologyBeamConfig()
        elif type(config) is CompactTopologyBeamConfig:
            chosen_config = config
        else:
            raise ValueError("topology beam config must be exactly CompactTopologyBeamConfig")

        self.problem = problem
        self.variant_indices = variant_indices
        self.sizes = sizes
        self.width_bound = width_bound
        self.base_seed = base_seed
        self.config = chosen_config
        self.direct_targets = direct_targets
        self._pairs = tuple(itertools.combinations(range(problem.size), 2))
        self._excluded: set[PairwiseRelationSignature] = set()
        self._solved = 0
        self._model, self._variables = self._build_model(coordinate_hint)

    def _build_model(
        self,
        coordinate_hint: DecodedPlacement | None,
    ) -> tuple[cp_model.CpModel, _TopologyBeamVariables]:
        model = cp_model.CpModel()
        area = sum(width * height for width, height in self.sizes)
        lower_bound = max(
            max((width for width, _height in self.sizes), default=0),
            (area + self.problem.outline_height - 1) // self.problem.outline_height,
        )
        outline_width = model.new_int_var(
            lower_bound,
            self.width_bound,
            "beam_outline_width",
        )
        x: list[cp_model.IntVar] = []
        y: list[cp_model.IntVar] = []
        x_intervals: list[cp_model.IntervalVar] = []
        y_intervals: list[cp_model.IntervalVar] = []
        for strip, (width, height) in enumerate(self.sizes):
            strip_x = model.new_int_var(0, self.width_bound - width, f"beam_x_{strip}")
            strip_y = model.new_int_var(
                0,
                self.problem.outline_height - height,
                f"beam_y_{strip}",
            )
            x.append(strip_x)
            y.append(strip_y)
            x_intervals.append(
                model.new_fixed_size_interval_var(
                    strip_x,
                    width,
                    f"beam_x_interval_{strip}",
                )
            )
            y_intervals.append(
                model.new_fixed_size_interval_var(
                    strip_y,
                    height,
                    f"beam_y_interval_{strip}",
                )
            )
            if coordinate_hint is not None:
                model.add_hint(
                    strip_x,
                    min(max(coordinate_hint.x[strip], 0), self.width_bound - width),
                )
                model.add_hint(
                    strip_y,
                    min(
                        max(coordinate_hint.y[strip], 0),
                        self.problem.outline_height - height,
                    ),
                )
        model.add_max_equality(
            outline_width,
            tuple(
                coordinate + width
                for coordinate, (width, _height) in zip(x, self.sizes, strict=True)
            ),
        )
        model.add_no_overlap_2d(x_intervals, y_intervals)

        relations: list[tuple[cp_model.IntVar, ...]] = []
        for first, second in self._pairs:
            first_width, first_height = self.sizes[first]
            second_width, second_height = self.sizes[second]
            literals: list[cp_model.IntVar] = []
            for name, lhs, rhs in (
                ("left", x[first] + first_width, x[second]),
                ("right", x[second] + second_width, x[first]),
                ("below", y[first] + first_height, y[second]),
                ("above", y[second] + second_height, y[first]),
            ):
                literal = model.new_bool_var(f"beam_{name}_{first}_{second}")
                model.add(lhs <= rhs).only_enforce_if(literal)
                model.add(lhs > rhs).only_enforce_if(literal.negated())
                literals.append(literal)
            relations.append(tuple(literals))

        if self.config.refine_width_first:
            hpwl_terms: list[cp_model.IntVar] = []
            for source, destination in self.problem.nets:
                delta_x = model.new_int_var(
                    0,
                    self.width_bound,
                    f"direct_dx{source}_{destination}",
                )
                delta_y = model.new_int_var(
                    0,
                    self.problem.outline_height,
                    f"direct_dy{source}_{destination}",
                )
                model.add_abs_equality(delta_x, x[source] - x[destination])
                model.add_abs_equality(delta_y, y[source] - y[destination])
                source_width, source_height = self.sizes[source]
                destination_width, destination_height = self.sizes[destination]
                model.add(
                    delta_x + delta_y
                    >= min(
                        min(source_width, destination_width),
                        min(source_height, destination_height),
                    )
                )
                hpwl_terms.extend((delta_x, delta_y))
            direct_successes: list[cp_model.IntVar] = []
            for target in self.direct_targets:
                direct = model.new_bool_var(f"beam_di{target.producer}_{target.consumer}")
                row_gap = (
                    y[target.consumer]
                    + target.consumer_row
                    - y[target.producer]
                    - target.producer_row
                )
                model.add(row_gap >= 1).only_enforce_if(direct)
                model.add(row_gap <= catalog.SORTER_MAX_REACH).only_enforce_if(direct)
                origin_delta = model.new_int_var(
                    -(target.consumer_span - 1),
                    target.producer_span - 1,
                    f"direct_origin_delta{target.producer}_{target.consumer}",
                )
                model.add(origin_delta == x[target.consumer] - x[target.producer]).only_enforce_if(
                    direct
                )
                model.add_allowed_assignments(
                    [origin_delta],
                    [(delta,) for delta in target.origin_deltas],
                ).only_enforce_if(direct)
                direct_successes.append(direct)
            width_weight = (
                len(hpwl_terms) * (self.width_bound + self.problem.outline_height)
                + _MISSED_DIRECT_WEIGHT * len(direct_successes)
                + 1
            )
            model.minimize(
                outline_width * width_weight
                + _HPWL_WEIGHT * sum(hpwl_terms)
                + _MISSED_DIRECT_WEIGHT * sum(direct.negated() for direct in direct_successes)
            )
        else:
            model.minimize(outline_width)
        return model, _TopologyBeamVariables(
            x=tuple(x),
            y=tuple(y),
            outline_width=outline_width,
            relations=tuple(relations),
        )

    def solve_next(
        self,
        *,
        absolute_deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
        stop_when_width_admits: Callable[[int], bool] | None = None,
    ) -> CompactTopologyCandidate | None:
        """Solve the next not-yet-excluded topology within fixed deterministic work."""
        if self._solved >= self.config.max_candidates:
            return None
        if absolute_deadline is not None and (
            type(absolute_deadline) is not float or not math.isfinite(absolute_deadline)
        ):
            raise ValueError("topology deadline must be a finite monotonic-clock float")
        if cancelled is not None and not callable(cancelled):
            raise ValueError("topology cancellation check must be callable")
        if stop_when_width_admits is not None and not callable(stop_when_width_admits):
            raise ValueError("topology width-admission check must be callable")
        if (cancelled is not None and cancelled()) or _deadline_reached(absolute_deadline):
            return None

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = self.base_seed % _RANDOM_SEED_MODULUS
        solver.parameters.randomize_search = False
        solver.parameters.max_deterministic_time = self.config.max_deterministic_time
        remaining = _remaining_wall_time(absolute_deadline)
        if remaining is not None:
            if remaining <= _DEADLINE_SAFETY_SECONDS:
                return None
            solver.parameters.max_time_in_seconds = remaining - _DEADLINE_SAFETY_SECONDS

        class WidthAdmission(cp_model.CpSolverSolutionCallback):
            """Stop once the exact incumbent admits already-routed evidence."""

            def on_solution_callback(self) -> None:
                assert stop_when_width_admits is not None
                if stop_when_width_admits(self.Value(self_outline_width)):
                    self.StopSearch()

        self_outline_width = self._variables.outline_width
        admission = WidthAdmission() if stop_when_width_admits is not None else None
        status_code = solver.solve(self._model, admission)
        if (cancelled is not None and cancelled()) or _deadline_reached(absolute_deadline):
            return None
        status = _status_from_solver(status_code)
        if status not in (CompactSeedStatus.FEASIBLE, CompactSeedStatus.OPTIMAL):
            return None

        x = tuple(solver.value(variable) for variable in self._variables.x)
        y = tuple(solver.value(variable) for variable in self._variables.y)
        signature = PairwiseRelationSignature(
            tuple(
                (
                    pair,
                    _solved_pairwise_relation(solver, relation_literals),
                )
                for pair, relation_literals in zip(
                    self._pairs,
                    self._variables.relations,
                    strict=True,
                )
            )
        )
        candidate = CompactTopologyCandidate(
            topology_index=self._solved,
            status=status,
            x=x,
            y=y,
            width=solver.value(self._variables.outline_width),
            used_height=max(
                (strip_y + height for strip_y, (_width, height) in zip(y, self.sizes, strict=True)),
                default=0,
            ),
            variant_indices=self.variant_indices,
            signature=signature,
            deterministic_time=solver.response_proto.deterministic_time,
        )
        self._solved += 1
        return candidate

    def exclude(self, signature: PairwiseRelationSignature) -> None:
        """Add one exact pairwise relation-signature no-good to the live model."""
        if not isinstance(signature, PairwiseRelationSignature):
            raise ValueError("topology no-good must be a pairwise relation signature")
        if tuple(pair for pair, _relation in signature.entries) != self._pairs:
            raise ValueError("topology no-good cardinality must match the beam problem")
        if signature in self._excluded:
            raise ValueError("topology relation signature was already excluded")
        differing: list[cp_model.LiteralT] = []
        for (_pair, values), literals in zip(
            signature.entries,
            self._variables.relations,
            strict=True,
        ):
            differing.extend(
                literal.negated() if value else literal
                for literal, value in zip(literals, values, strict=True)
            )
        self._model.add_bool_or(differing)
        self._excluded.add(signature)


@dataclass(frozen=True, slots=True)
class _ModelVariables:
    x: tuple[cp_model.IntVar, ...]
    y: tuple[cp_model.IntVar, ...]
    widths: tuple[cp_model.IntVar, ...]
    heights: tuple[cp_model.IntVar, ...]
    variants: tuple[cp_model.IntVar, ...]
    selected: tuple[tuple[cp_model.IntVar, ...], ...]
    positive_ranks: tuple[cp_model.IntVar, ...]
    negative_ranks: tuple[cp_model.IntVar, ...]
    outline_width: cp_model.IntVar
    port_offsets: tuple[
        tuple[cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar], ...
    ]
    direct_successes: tuple[tuple[tuple[int, int], cp_model.IntVar], ...]
    objective: cp_model.LinearExpr
    width_weight: int
    secondary_upper_bound: int


@dataclass(frozen=True, slots=True)
class _ModelPlan:
    size_tables: tuple[tuple[tuple[int, int], ...], ...]
    max_width: int
    area_width_lower_bound: int
    port_tables: tuple[tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]], ...]
    net_weights: tuple[int, ...]
    direct_groups: tuple[tuple[tuple[int, int], tuple[VariantDirectInsertTarget, ...]], ...]
    tie_coefficients: tuple[tuple[int, int, int, int, int], ...]
    secondary_upper_bound: int
    width_weight: int


def solve_compact_seed(
    problem: PlacementProblem,
    *,
    base_seed: int,
    attempt: int,
    config: CompactSeedConfig | None = None,
    direct_eligibility: tuple[VariantDirectInsertTarget, ...] = (),
    absolute_deadline: float | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> CompactSeedResult:
    """Return one validated zero-gap seed for ``problem``, never a final placement.

    ``absolute_deadline`` is a monotonic-clock deadline.  It caps the solver's wall
    time in addition to the deterministic work cap.  Cancellation is checked before
    model construction, immediately before the blocking solve, and after it returns.
    """

    if not isinstance(problem, PlacementProblem):
        raise ValueError("compact seed problem must be a PlacementProblem")
    if type(base_seed) is not int:
        raise ValueError("base seed must be an integer")
    if type(attempt) is not int or attempt < 0:
        raise ValueError("attempt must be a non-negative integer")
    if config is None:
        chosen_config = CompactSeedConfig()
    elif type(config) is CompactSeedConfig:
        chosen_config = config
    else:
        raise ValueError("compact seed config must be exactly CompactSeedConfig")
    if not isinstance(direct_eligibility, tuple) or any(
        not isinstance(entry, VariantDirectInsertTarget) for entry in direct_eligibility
    ):
        raise ValueError("direct eligibility must be an immutable tuple")
    if absolute_deadline is not None and (
        type(absolute_deadline) is not float or not math.isfinite(absolute_deadline)
    ):
        raise ValueError("absolute deadline must be a finite monotonic-clock float")
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancellation check must be callable")

    stage_seed = derive_stage_seed(base_seed, attempt)
    solver_seed = stage_seed % _RANDOM_SEED_MODULUS
    is_cancelled: Callable[[], bool] = (lambda: False) if cancelled is None else cancelled
    if is_cancelled() or _deadline_reached(absolute_deadline):
        return _empty_result(CompactSeedStatus.CANCELLED, solver_seed, "CANCELLED")

    _validate_direct_eligibility(problem, direct_eligibility)
    plan = _prepare_model_plan(problem, direct_eligibility, stage_seed)
    if problem.size == 0:
        state = AnnealState(
            pair=SequencePair((), ()),
            gaps=GapProfile.zero(0),
            variant_indices=(),
            base_seed=base_seed,
            stage_index=0,
        )
        diagnostics = CompactSeedDiagnostics(
            solver_seed=solver_seed,
            status_name="OPTIMAL",
            width_weight=1,
            secondary_upper_bound=0,
            objective_value=0,
            best_objective_bound=0,
            solved_x=(),
            solved_y=(),
            solved_sizes=(),
            solved_width=0,
            decoded_width=0,
            decoded_height=0,
            positive_ranks=(),
            negative_ranks=(),
        )
        return CompactSeedResult(CompactSeedStatus.OPTIMAL, state, diagnostics)

    model, variables = _build_model(problem, plan)
    if is_cancelled() or _deadline_reached(absolute_deadline):
        return _empty_result(
            CompactSeedStatus.CANCELLED,
            solver_seed,
            "CANCELLED",
            variables.width_weight,
            variables.secondary_upper_bound,
        )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = solver_seed
    solver.parameters.randomize_search = False
    solver.parameters.cp_model_presolve = True
    solver.parameters.max_deterministic_time = chosen_config.max_deterministic_time
    remaining = _remaining_wall_time(absolute_deadline)
    if remaining is not None:
        if remaining <= _DEADLINE_SAFETY_SECONDS:
            return _empty_result(
                CompactSeedStatus.CANCELLED,
                solver_seed,
                "CANCELLED",
                variables.width_weight,
                variables.secondary_upper_bound,
            )
        solver.parameters.max_time_in_seconds = remaining - _DEADLINE_SAFETY_SECONDS

    status_code, cancellation_requested = _solve_interruptibly(
        solver,
        model,
        cancelled,
    )
    if cancellation_requested or is_cancelled() or _deadline_reached(absolute_deadline):
        return _diagnostic_empty_result(
            CompactSeedStatus.CANCELLED,
            "CANCELLED",
            solver_seed,
            solver,
            variables,
        )

    status = _status_from_solver(status_code)
    status_name = solver.status_name(status_code).upper()
    if status not in (CompactSeedStatus.OPTIMAL, CompactSeedStatus.FEASIBLE):
        return _diagnostic_empty_result(status, status_name, solver_seed, solver, variables)

    return _extract_validated_result(
        problem,
        direct_eligibility,
        base_seed,
        solver_seed,
        status,
        status_name,
        solver,
        variables,
    )


def _prepare_model_plan(
    problem: PlacementProblem,
    direct_eligibility: tuple[VariantDirectInsertTarget, ...],
    stage_seed: int,
) -> _ModelPlan:
    """Validate every integer bound before constructing an OR-Tools object."""

    size_tables = _selected_size_tables(problem)
    size = problem.size
    height = problem.outline_height
    _require_cp_nonnegative(height, "outline height")
    _require_cp_nonnegative(size - 1, "sequence rank domain", allow_negative_one=True)

    for strip, table in enumerate(size_tables):
        _require_cp_nonnegative(len(table) - 1, f"variant domain for strip {strip}")
        for variant, (width, strip_height) in enumerate(table):
            _require_cp_nonnegative(width, f"width for strip {strip} variant {variant}")
            _require_cp_nonnegative(
                strip_height,
                f"height for strip {strip} variant {variant}",
            )

    max_width = sum(max(width for width, _strip_height in table) for table in size_tables)
    _require_cp_nonnegative(max_width, "maximum width")
    _require_cp_nonnegative(2 * max_width, "doubled x coordinate domain")
    _require_cp_nonnegative(2 * height, "doubled y coordinate domain")
    area_width_lower_bound = (problem.area_lower_bound + height - 1) // height
    _require_cp_nonnegative(area_width_lower_bound, "area-derived width lower bound")

    port_tables = tuple(
        _net_port_offset_tables(problem, net_index) for net_index in range(len(problem.nets))
    )
    for net_index, (source_offsets, destination_offsets) in enumerate(port_tables):
        for offset in (*source_offsets, *destination_offsets):
            _require_cp_signed(offset[0], f"net {net_index} x port offset")
            _require_cp_signed(offset[1], f"net {net_index} y port offset")

    net_weights = tuple(
        _HPWL_WEIGHT * (1 + _stable_coefficient(stage_seed, net_index, 0, 3))
        for net_index in range(len(problem.nets))
    )
    by_key: dict[tuple[int, int], list[VariantDirectInsertTarget]] = {}
    for entry in direct_eligibility:
        by_key.setdefault(entry.target.key, []).append(entry)
    direct_groups = tuple((key, tuple(by_key[key])) for key in sorted(by_key))
    tie_coefficients = tuple(
        (
            _stable_coefficient(stage_seed, strip, 1, 7),
            _stable_coefficient(stage_seed, strip, 2, 7),
            _stable_coefficient(stage_seed, strip, 3, 7),
            _stable_coefficient(stage_seed, strip, 4, 7),
            _stable_coefficient(stage_seed, strip, 5, 7),
        )
        for strip in range(size)
    )

    secondary_upper_bound = sum(weight * (2 * max_width + 2 * height) for weight in net_weights)
    secondary_upper_bound += _MISSED_DIRECT_WEIGHT * len(direct_groups)
    secondary_upper_bound += sum(
        x_coefficient * max_width
        + y_coefficient * height
        + variant_coefficient * (len(size_tables[strip]) - 1)
        + (positive_coefficient + negative_coefficient) * (size - 1)
        for strip, (
            x_coefficient,
            y_coefficient,
            variant_coefficient,
            positive_coefficient,
            negative_coefficient,
        ) in enumerate(tie_coefficients)
    )
    _require_cp_nonnegative(secondary_upper_bound, "secondary objective upper bound")
    width_weight = secondary_upper_bound + 1
    _require_cp_nonnegative(width_weight, "width objective coefficient")
    objective_upper_bound = width_weight * max_width + secondary_upper_bound
    _require_cp_nonnegative(objective_upper_bound, "full objective upper bound")
    return _ModelPlan(
        size_tables=size_tables,
        max_width=max_width,
        area_width_lower_bound=area_width_lower_bound,
        port_tables=port_tables,
        net_weights=net_weights,
        direct_groups=direct_groups,
        tie_coefficients=tie_coefficients,
        secondary_upper_bound=secondary_upper_bound,
        width_weight=width_weight,
    )


def _build_model(
    problem: PlacementProblem,
    plan: _ModelPlan,
) -> tuple[cp_model.CpModel, _ModelVariables]:
    model = cp_model.CpModel()
    size_tables = plan.size_tables
    size = problem.size
    height = problem.outline_height
    max_width = plan.max_width

    x: list[cp_model.IntVar] = []
    y: list[cp_model.IntVar] = []
    widths: list[cp_model.IntVar] = []
    heights: list[cp_model.IntVar] = []
    variants: list[cp_model.IntVar] = []
    selected: list[tuple[cp_model.IntVar, ...]] = []
    for strip, table in enumerate(size_tables):
        variant = model.new_int_var(0, len(table) - 1, f"variant_{strip}")
        one_hot = tuple(
            model.new_bool_var(f"selected_{strip}_{index}") for index in range(len(table))
        )
        model.add_exactly_one(one_hot)
        model.add(variant == sum(index * literal for index, literal in enumerate(one_hot)))
        width_values = [width for width, _strip_height in table]
        height_values = [strip_height for _width, strip_height in table]
        width = model.new_int_var(min(width_values), max(width_values), f"width_{strip}")
        strip_height = model.new_int_var(min(height_values), max(height_values), f"height_{strip}")
        model.add_element(variant, width_values, width)
        model.add_element(variant, height_values, strip_height)
        strip_x = model.new_int_var(0, max_width, f"x_{strip}")
        strip_y = model.new_int_var(0, height, f"y_{strip}")
        model.add(strip_y + strip_height <= height)
        x.append(strip_x)
        y.append(strip_y)
        widths.append(width)
        heights.append(strip_height)
        variants.append(variant)
        selected.append(one_hot)

    positive_ranks = tuple(
        model.new_int_var(0, size - 1, f"positive_rank_{strip}") for strip in range(size)
    )
    negative_ranks = tuple(
        model.new_int_var(0, size - 1, f"negative_rank_{strip}") for strip in range(size)
    )
    model.add_all_different(positive_ranks)
    model.add_all_different(negative_ranks)
    for first in range(size):
        for second in range(first + 1, size):
            positive_before = model.new_bool_var(f"positive_before_{first}_{second}")
            negative_before = model.new_bool_var(f"negative_before_{first}_{second}")
            model.add(positive_ranks[first] < positive_ranks[second]).only_enforce_if(
                positive_before
            )
            model.add(positive_ranks[first] > positive_ranks[second]).only_enforce_if(
                positive_before.negated()
            )
            model.add(negative_ranks[first] < negative_ranks[second]).only_enforce_if(
                negative_before
            )
            model.add(negative_ranks[first] > negative_ranks[second]).only_enforce_if(
                negative_before.negated()
            )
            model.add(x[first] + widths[first] <= x[second]).only_enforce_if(
                (positive_before, negative_before)
            )
            model.add(x[second] + widths[second] <= x[first]).only_enforce_if(
                (positive_before.negated(), negative_before.negated())
            )
            model.add(y[second] + heights[second] <= y[first]).only_enforce_if(
                (positive_before, negative_before.negated())
            )
            model.add(y[first] + heights[first] <= y[second]).only_enforce_if(
                (positive_before.negated(), negative_before)
            )

    outline_width = model.new_int_var(0, max_width, "outline_width")
    model.add(outline_width >= plan.area_width_lower_bound)
    for strip in range(size):
        model.add(outline_width >= x[strip] + widths[strip])

    secondary_terms: list[cp_model.LinearExpr] = []
    port_offsets: list[
        tuple[cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar]
    ] = []
    for net_index, (
        (source, destination),
        (source_offsets, destination_offsets),
        weight,
    ) in enumerate(zip(problem.nets, plan.port_tables, plan.net_weights, strict=True)):
        source_x = _element_variable(
            model, variants[source], source_offsets, 0, f"source_x_{net_index}"
        )
        source_y = _element_variable(
            model, variants[source], source_offsets, 1, f"source_y_{net_index}"
        )
        destination_x = _element_variable(
            model, variants[destination], destination_offsets, 0, f"destination_x_{net_index}"
        )
        destination_y = _element_variable(
            model, variants[destination], destination_offsets, 1, f"destination_y_{net_index}"
        )
        port_offsets.append((source_x, source_y, destination_x, destination_y))
        absolute_x = model.new_int_var(0, 2 * max_width, f"net_x_{net_index}")
        absolute_y = model.new_int_var(0, 2 * height, f"net_y_{net_index}")
        model.add_abs_equality(
            absolute_x,
            x[source] + source_x - x[destination] - destination_x,
        )
        model.add_abs_equality(
            absolute_y,
            y[source] + source_y - y[destination] - destination_y,
        )
        secondary_terms.extend((weight * absolute_x, weight * absolute_y))

    direct_successes: list[tuple[tuple[int, int], cp_model.IntVar]] = []
    for direct_index, (key, entries) in enumerate(plan.direct_groups):
        successes: list[cp_model.IntVar] = []
        for combo_index, entry in enumerate(entries):
            target = entry.target
            success = model.new_bool_var(f"direct_{direct_index}_{combo_index}")
            model.add_implication(success, selected[target.producer][entry.producer_variant])
            model.add_implication(success, selected[target.consumer][entry.consumer_variant])
            row_gap = (
                y[target.consumer] + target.consumer_row - y[target.producer] - target.producer_row
            )
            model.add(row_gap >= 1).only_enforce_if(success)
            model.add(row_gap <= catalog.SORTER_MAX_REACH).only_enforce_if(success)
            origin_delta = model.new_int_var(
                -(target.consumer_span - 1),
                target.producer_span - 1,
                f"direct_origin_delta_{direct_index}_{combo_index}",
            )
            model.add(origin_delta == x[target.consumer] - x[target.producer]).only_enforce_if(
                success
            )
            model.add_allowed_assignments(
                [origin_delta],
                [(delta,) for delta in target.origin_deltas],
            ).only_enforce_if(success)
            successes.append(success)
            direct_successes.append((key, success))
        missed = model.new_bool_var(f"direct_missed_{direct_index}")
        model.add(missed + sum(successes) == 1)
        secondary_terms.append(_MISSED_DIRECT_WEIGHT * missed)

    for strip, (
        x_coefficient,
        y_coefficient,
        variant_coefficient,
        positive_coefficient,
        negative_coefficient,
    ) in enumerate(plan.tie_coefficients):
        secondary_terms.extend(
            (
                x_coefficient * x[strip],
                y_coefficient * y[strip],
                variant_coefficient * variants[strip],
                positive_coefficient * positive_ranks[strip],
                negative_coefficient * negative_ranks[strip],
            )
        )

    objective = plan.width_weight * outline_width + sum(secondary_terms)
    model.minimize(objective)
    return model, _ModelVariables(
        x=tuple(x),
        y=tuple(y),
        widths=tuple(widths),
        heights=tuple(heights),
        variants=tuple(variants),
        selected=tuple(selected),
        positive_ranks=positive_ranks,
        negative_ranks=negative_ranks,
        outline_width=outline_width,
        port_offsets=tuple(port_offsets),
        direct_successes=tuple(direct_successes),
        objective=objective,
        width_weight=plan.width_weight,
        secondary_upper_bound=plan.secondary_upper_bound,
    )


def _selected_size_tables(
    problem: PlacementProblem,
) -> tuple[tuple[tuple[int, int], ...], ...]:
    if not problem.variant_tables:
        return tuple((size,) for size in problem.sizes)
    tables: list[tuple[tuple[int, int], ...]] = []
    zero = [0] * problem.size
    for strip, variants in enumerate(problem.variant_tables):
        selected: list[tuple[int, int]] = []
        for variant in range(len(variants)):
            indices = zero.copy()
            indices[strip] = variant
            selected.append(problem.selected_sizes(tuple(indices))[strip])
        tables.append(tuple(selected))
    return tuple(tables)


def _net_port_offset_tables(
    problem: PlacementProblem,
    net_index: int,
) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    source, destination = problem.nets[net_index]
    if not problem.variant_tables or not problem.logical_net_ids:
        source_count = len(problem.variant_tables[source]) if problem.variant_tables else 1
        destination_count = (
            len(problem.variant_tables[destination]) if problem.variant_tables else 1
        )
        return ((0, 0),) * source_count, ((0, 0),) * destination_count
    logical = problem.logical_net_ids[net_index]
    destination_group_key = (
        logical.destination_family.group_key if logical.destination_family is not None else None
    )
    return (
        tuple(
            _authoritative_port_offset(
                variant,
                logical.item,
                "output",
                destination_group_key=destination_group_key,
            )
            for variant in problem.variant_tables[source]
        ),
        tuple(
            _authoritative_port_offset(variant, logical.item, "input")
            for variant in problem.variant_tables[destination]
        ),
    )


def _authoritative_port_offset(
    variant: StripVariant,
    item: str,
    kind: str,
    *,
    destination_group_key: str | None = None,
) -> tuple[int, int]:
    plans = tuple(
        plan
        for plan in variant.attachment_plan
        if plan.lane.kind == kind
        and item in plan.lane.items
        and (
            kind != "output"
            or destination_group_key is None
            or destination_group_key in plan.lane.destination_group_keys
        )
    )
    if len(plans) != 1:
        raise ValueError(f"variant must expose exactly one authoritative {kind} port for {item}")
    attachments = tuple(
        attachment for attachment in plans[0].attachments if attachment.item == item
    )
    if len(attachments) != 1:
        raise ValueError(
            f"variant must expose exactly one authoritative {kind} attachment for {item}"
        )
    cell = attachments[0].cell
    if not 0 <= cell[0] < variant.box_width or not 0 <= cell[1] < variant.box_height:
        raise ValueError("authoritative port attachment must lie inside its variant box")
    return cell


def _element_variable(
    model: cp_model.CpModel,
    variant: cp_model.IntVar,
    offsets: tuple[tuple[int, int], ...],
    axis: int,
    name: str,
) -> cp_model.IntVar:
    values = [offset[axis] for offset in offsets]
    result = model.new_int_var(min(values), max(values), name)
    model.add_element(variant, values, result)
    return result


def _validate_direct_eligibility(
    problem: PlacementProblem,
    eligibility: tuple[VariantDirectInsertTarget, ...],
) -> None:
    seen: set[tuple[int, int, tuple[int, int]]] = set()
    net_pairs = set(problem.nets)
    size_tables = _selected_size_tables(problem)
    for entry in eligibility:
        target = entry.target
        if not 0 <= target.producer < problem.size or not 0 <= target.consumer < problem.size:
            raise ValueError("direct eligibility endpoints must identify placement strips")
        if (target.producer, target.consumer) not in net_pairs:
            raise ValueError("direct eligibility must identify an existing directed placement net")
        if entry.producer_variant >= len(size_tables[target.producer]):
            raise ValueError("producer variant is outside its production variant table")
        if entry.consumer_variant >= len(size_tables[target.consumer]):
            raise ValueError("consumer variant is outside its production variant table")
        producer_width, producer_height = size_tables[target.producer][entry.producer_variant]
        consumer_width, consumer_height = size_tables[target.consumer][entry.consumer_variant]
        if (
            target.producer_row >= producer_height
            or target.consumer_row >= consumer_height
            or target.producer_span > producer_width
            or target.consumer_span > consumer_width
        ):
            raise ValueError("direct target geometry must lie inside its eligible variant boxes")
        identity = (entry.producer_variant, entry.consumer_variant, target.key)
        if identity in seen:
            raise ValueError("direct eligibility must not duplicate a variant pair and target key")
        seen.add(identity)


def _stable_coefficient(seed: int, index: int, channel: int, maximum: int) -> int:
    mixed = derive_stage_seed(seed, index * 8 + channel)
    return 1 + mixed % maximum


def _require_cp_nonnegative(
    value: int,
    name: str,
    *,
    allow_negative_one: bool = False,
) -> None:
    lower_bound = -1 if allow_negative_one else 0
    if value < lower_bound or value > _CP_INT_MAX:
        raise ValueError(f"{name} exceeds signed 64-bit CP-SAT limits")


def _require_cp_signed(value: int, name: str) -> None:
    if not -_CP_INT_MAX <= value <= _CP_INT_MAX:
        raise ValueError(f"{name} exceeds signed 64-bit CP-SAT limits")


def _solve_interruptibly(
    solver: cp_model.CpSolver,
    model: cp_model.CpModel,
    cancelled: Callable[[], bool] | None,
) -> tuple[cp_model.CpSolverStatus, bool]:
    if cancelled is None:
        return solver.solve(model), False

    finished = threading.Event()
    cancellation_requested = threading.Event()
    watcher_errors: list[BaseException] = []

    def watch_cancellation() -> None:
        while not finished.wait(0.005):
            try:
                should_cancel = cancelled()
            except BaseException as error:
                watcher_errors.append(error)
                with contextlib.suppress(BaseException):
                    solver.stop_search()
                return
            if should_cancel:
                cancellation_requested.set()
                try:
                    solver.stop_search()
                except BaseException as error:
                    watcher_errors.append(error)
                return

    watcher = threading.Thread(
        target=watch_cancellation,
        name="compact-seed-cancellation",
    )
    watcher.start()
    try:
        status = solver.solve(model)
    finally:
        finished.set()
        watcher.join()
    if watcher_errors:
        raise watcher_errors[0]
    return status, cancellation_requested.is_set()


def _status_from_solver(status: cp_model.CpSolverStatus) -> CompactSeedStatus:
    if status == cp_model.OPTIMAL:
        return CompactSeedStatus.OPTIMAL
    if status == cp_model.FEASIBLE:
        return CompactSeedStatus.FEASIBLE
    if status == cp_model.INFEASIBLE:
        return CompactSeedStatus.INFEASIBLE
    if status == cp_model.MODEL_INVALID:
        return CompactSeedStatus.INVALID
    return CompactSeedStatus.UNKNOWN


def _extract_validated_result(
    problem: PlacementProblem,
    direct_eligibility: tuple[VariantDirectInsertTarget, ...],
    base_seed: int,
    solver_seed: int,
    status: CompactSeedStatus,
    status_name: str,
    solver: cp_model.CpSolver,
    variables: _ModelVariables,
) -> CompactSeedResult:
    positive_ranks = tuple(solver.value(variable) for variable in variables.positive_ranks)
    negative_ranks = tuple(solver.value(variable) for variable in variables.negative_ranks)
    pair = SequencePair(
        tuple(sorted(range(problem.size), key=positive_ranks.__getitem__)),
        tuple(sorted(range(problem.size), key=negative_ranks.__getitem__)),
    )
    variant_indices = tuple(solver.value(variable) for variable in variables.variants)
    state = AnnealState(
        pair=pair,
        gaps=GapProfile.zero(problem.size),
        variant_indices=variant_indices,
        base_seed=base_seed,
        stage_index=0,
    )
    solved_x = tuple(solver.value(variable) for variable in variables.x)
    solved_y = tuple(solver.value(variable) for variable in variables.y)
    solved_sizes = tuple(
        (solver.value(width), solver.value(height))
        for width, height in zip(variables.widths, variables.heights, strict=True)
    )
    selected_port_offsets = tuple(
        (
            solver.value(source_x),
            solver.value(source_y),
            solver.value(destination_x),
            solver.value(destination_y),
        )
        for source_x, source_y, destination_x, destination_y in variables.port_offsets
    )
    cp_direct_keys = frozenset(
        key for key, success in variables.direct_successes if solver.value(success)
    )

    validation_error: str | None = None
    decoded: DecodedPlacement | None = None
    try:
        if solved_sizes != problem.selected_sizes(variant_indices):
            raise ValueError("CP variant dimensions disagree with production selection")
        if not _coordinates_are_non_overlapping(solved_x, solved_y, solved_sizes):
            raise ValueError("CP advisory coordinates overlap")
        if any(
            y + strip_height > problem.outline_height
            for y, (_width, strip_height) in zip(solved_y, solved_sizes, strict=True)
        ):
            raise ValueError("CP advisory coordinates exceed the fixed outline height")
        decoded = decode_state(problem, state)
        if decoded.used_height > problem.outline_height:
            raise ValueError("zero-gap sequence decode exceeds the fixed outline height")
        if decoded.gap_area != 0 or state.gaps != GapProfile.zero(problem.size):
            raise ValueError("compact seed decode contains non-zero gaps")
        if not _coordinates_are_non_overlapping(decoded.x, decoded.y, solved_sizes):
            raise ValueError("zero-gap sequence decode overlaps")
    except ValueError as error:
        validation_error = str(error)

    decoded_direct_keys = (
        _decoded_direct_keys(decoded, variant_indices, direct_eligibility)
        if decoded is not None and validation_error is None
        else frozenset()
    )
    diagnostics = CompactSeedDiagnostics(
        solver_seed=solver_seed,
        status_name=status_name,
        width_weight=variables.width_weight,
        secondary_upper_bound=variables.secondary_upper_bound,
        objective_value=solver.value(variables.objective),
        best_objective_bound=round(solver.best_objective_bound),
        branches=solver.num_branches,
        conflicts=solver.num_conflicts,
        deterministic_time=solver.response_proto.deterministic_time,
        solved_x=solved_x,
        solved_y=solved_y,
        solved_sizes=solved_sizes,
        solved_width=solver.value(variables.outline_width),
        decoded_width=decoded.width if decoded is not None else None,
        decoded_height=decoded.used_height if decoded is not None else None,
        positive_ranks=positive_ranks,
        negative_ranks=negative_ranks,
        selected_variant_ids=problem.selected_variant_ids(variant_indices),
        selected_port_offsets=selected_port_offsets,
        cp_direct_keys=cp_direct_keys,
        decoded_direct_keys=decoded_direct_keys,
        validation_error=validation_error,
    )
    if validation_error is not None:
        return CompactSeedResult(CompactSeedStatus.INVALID, None, diagnostics)
    return CompactSeedResult(status, state, diagnostics)


def _decoded_direct_keys(
    decoded: DecodedPlacement,
    variant_indices: tuple[int, ...],
    eligibility: tuple[VariantDirectInsertTarget, ...],
) -> frozenset[tuple[int, int]]:
    realized: set[tuple[int, int]] = set()
    for entry in eligibility:
        target = entry.target
        if (
            variant_indices[target.producer] == entry.producer_variant
            and variant_indices[target.consumer] == entry.consumer_variant
            and _target_is_direct(decoded, target)
        ):
            realized.add(target.key)
    return frozenset(realized)


def _target_is_direct(decoded: DecodedPlacement, target: DirectInsertTarget) -> bool:
    row_gap = (
        decoded.y[target.consumer]
        + target.consumer_row
        - decoded.y[target.producer]
        - target.producer_row
    )
    return (
        1 <= row_gap <= catalog.SORTER_MAX_REACH
        and decoded.x[target.consumer] - decoded.x[target.producer] in target.origin_deltas
    )


def _coordinates_are_non_overlapping(
    x: tuple[int, ...],
    y: tuple[int, ...],
    sizes: tuple[tuple[int, int], ...],
) -> bool:
    for first in range(len(sizes)):
        for second in range(first + 1, len(sizes)):
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


def _diagnostic_empty_result(
    status: CompactSeedStatus,
    status_name: str,
    solver_seed: int,
    solver: cp_model.CpSolver,
    variables: _ModelVariables,
) -> CompactSeedResult:
    diagnostics = CompactSeedDiagnostics(
        solver_seed=solver_seed,
        status_name=status_name,
        width_weight=variables.width_weight,
        secondary_upper_bound=variables.secondary_upper_bound,
        branches=_safe_solver_int(solver, "num_branches"),
        conflicts=_safe_solver_int(solver, "num_conflicts"),
        deterministic_time=_safe_deterministic_time(solver),
    )
    return CompactSeedResult(status, None, diagnostics)


def _empty_result(
    status: CompactSeedStatus,
    solver_seed: int,
    status_name: str,
    width_weight: int = 0,
    secondary_upper_bound: int = 0,
) -> CompactSeedResult:
    return CompactSeedResult(
        status,
        None,
        CompactSeedDiagnostics(
            solver_seed=solver_seed,
            status_name=status_name,
            width_weight=width_weight,
            secondary_upper_bound=secondary_upper_bound,
        ),
    )


def _safe_solver_int(solver: cp_model.CpSolver, attribute: str) -> int:
    try:
        return int(getattr(solver, attribute))
    except RuntimeError:
        return 0


def _safe_deterministic_time(solver: cp_model.CpSolver) -> float:
    try:
        return solver.response_proto.deterministic_time
    except RuntimeError:
        return 0.0


def _deadline_reached(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _remaining_wall_time(deadline: float | None) -> float | None:
    return None if deadline is None else max(0.0, deadline - time.monotonic())


__all__ = [
    "CompactSeedConfig",
    "CompactSeedDiagnostics",
    "CompactSeedResult",
    "CompactSeedStatus",
    "VariantDirectInsertTarget",
    "solve_compact_seed",
]
