"""Deterministic routing-aware CP-SAT seeds for sequence-pair search.

The CP coordinates in this module exist only to construct a compact sequence pair.
The returned zero-gap :class:`AnnealState` is decoded and validated again through the
production sequence-pair representation; no CP placement is exposed as a layout.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from ortools.sat.python import cp_model

from flab2bp.dsp import catalog
from flab2bp.layout.freeform import LAMBDA_HPWL, MU_DIRECT
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

    max_deterministic_time: float = 4.0

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
    chosen_config = config or CompactSeedConfig()
    if not isinstance(chosen_config, CompactSeedConfig):
        raise ValueError("compact seed config must be a CompactSeedConfig")
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
    is_cancelled = cancelled or (lambda: False)
    if is_cancelled() or _deadline_reached(absolute_deadline):
        return _empty_result(CompactSeedStatus.CANCELLED, solver_seed, "CANCELLED")

    _validate_direct_eligibility(problem, direct_eligibility)
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

    model, variables = _build_model(problem, direct_eligibility, stage_seed)
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

    status_code = solver.solve(model)
    if is_cancelled() or _deadline_reached(absolute_deadline):
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


def _build_model(
    problem: PlacementProblem,
    direct_eligibility: tuple[VariantDirectInsertTarget, ...],
    stage_seed: int,
) -> tuple[cp_model.CpModel, _ModelVariables]:
    model = cp_model.CpModel()
    size_tables = _selected_size_tables(problem)
    size = problem.size
    height = problem.outline_height
    max_width = sum(max(width for width, _strip_height in table) for table in size_tables)
    if max_width > _CP_INT_MAX:
        raise ValueError("compact seed width domain exceeds signed 64-bit CP-SAT limits")

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
    area_width_lower_bound = (problem.area_lower_bound + height - 1) // height
    model.add(outline_width >= area_width_lower_bound)
    for strip in range(size):
        model.add(outline_width >= x[strip] + widths[strip])

    secondary_terms: list[cp_model.LinearExpr] = []
    secondary_upper_bound = 0
    port_offsets: list[
        tuple[cp_model.IntVar, cp_model.IntVar, cp_model.IntVar, cp_model.IntVar]
    ] = []
    for net_index, (source, destination) in enumerate(problem.nets):
        source_offsets, destination_offsets = _net_port_offset_tables(problem, net_index)
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
        weight = LAMBDA_HPWL * (1 + _stable_coefficient(stage_seed, net_index, 0, 3))
        secondary_terms.extend((weight * absolute_x, weight * absolute_y))
        secondary_upper_bound += weight * (2 * max_width + 2 * height)

    direct_successes: list[tuple[tuple[int, int], cp_model.IntVar]] = []
    by_key: dict[tuple[int, int], list[VariantDirectInsertTarget]] = {}
    for entry in direct_eligibility:
        by_key.setdefault(entry.target.key, []).append(entry)
    for direct_index, key in enumerate(sorted(by_key)):
        successes: list[cp_model.IntVar] = []
        for combo_index, entry in enumerate(by_key[key]):
            target = entry.target
            success = model.new_bool_var(f"direct_{direct_index}_{combo_index}")
            model.add_implication(success, selected[target.producer][entry.producer_variant])
            model.add_implication(success, selected[target.consumer][entry.consumer_variant])
            row_gap = (
                y[target.consumer] + target.consumer_row - y[target.producer] - target.producer_row
            )
            model.add(row_gap >= 1).only_enforce_if(success)
            model.add(row_gap <= catalog.SORTER_MAX_REACH).only_enforce_if(success)
            model.add(
                x[target.producer] <= x[target.consumer] + target.consumer_span - 1
            ).only_enforce_if(success)
            model.add(
                x[target.consumer] <= x[target.producer] + target.producer_span - 1
            ).only_enforce_if(success)
            successes.append(success)
            direct_successes.append((key, success))
        missed = model.new_bool_var(f"direct_missed_{direct_index}")
        model.add(missed + sum(successes) == 1)
        secondary_terms.append(MU_DIRECT * missed)
        secondary_upper_bound += MU_DIRECT

    for strip in range(size):
        x_coefficient = _stable_coefficient(stage_seed, strip, 1, 7)
        y_coefficient = _stable_coefficient(stage_seed, strip, 2, 7)
        variant_coefficient = _stable_coefficient(stage_seed, strip, 3, 7)
        positive_coefficient = _stable_coefficient(stage_seed, strip, 4, 7)
        negative_coefficient = _stable_coefficient(stage_seed, strip, 5, 7)
        secondary_terms.extend(
            (
                x_coefficient * x[strip],
                y_coefficient * y[strip],
                variant_coefficient * variants[strip],
                positive_coefficient * positive_ranks[strip],
                negative_coefficient * negative_ranks[strip],
            )
        )
        secondary_upper_bound += (
            x_coefficient * max_width
            + y_coefficient * height
            + variant_coefficient * (len(size_tables[strip]) - 1)
            + (positive_coefficient + negative_coefficient) * (size - 1)
        )

    width_weight = secondary_upper_bound + 1
    objective = width_weight * outline_width + sum(secondary_terms)
    objective_upper_bound = width_weight * max_width + secondary_upper_bound
    if objective_upper_bound > _CP_INT_MAX:
        raise ValueError("compact seed objective exceeds signed 64-bit CP-SAT limits")
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
        width_weight=width_weight,
        secondary_upper_bound=secondary_upper_bound,
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
        and decoded.x[target.producer] <= decoded.x[target.consumer] + target.consumer_span - 1
        and decoded.x[target.consumer] <= decoded.x[target.producer] + target.producer_span - 1
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
