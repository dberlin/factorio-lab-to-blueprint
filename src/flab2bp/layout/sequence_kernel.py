"""Exact decode-and-score backends for sequence-pair annealing."""

from __future__ import annotations

import sys
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol, runtime_checkable

import flab2bp.layout.sequence_pair as sequence_pair
from flab2bp.dsp import catalog

type _DecodeScore = Callable[
    [
        array[int],
        array[int],
        array[int],
        array[int],
        array[int],
        array[int],
        array[float],
        array[float],
        array[int],
        array[int],
        bytearray,
        bytearray,
        array[int],
        array[int],
        array[int],
        array[int],
        int,
        int,
        int,
    ],
    tuple[
        array[int],
        array[int],
        array[int],
        array[int],
        int,
        int,
        int,
        int,
        float,
        float,
        int,
        int,
    ],
]

_compiled_decode_score: _DecodeScore | None

try:
    from flab2bp.layout._sequence_kernel import decode_score as _compiled_decode_score
except ImportError:
    _compiled_decode_score = None

_SIGNED_64_MAX = 2**63 - 1
_BUFFER_INDEX_MAX = min(_SIGNED_64_MAX, sys.maxsize)

BackendName = Literal["python", "cython"]


@runtime_checkable
class SequenceKernel(Protocol):
    """Internal exact scoring boundary used by one annealing stage."""

    backend: ClassVar[BackendName]

    def score_state(
        self,
        state: sequence_pair.AnnealState,
        *,
        direct_targets: tuple[sequence_pair.DirectInsertTarget, ...] | None = None,
    ) -> sequence_pair.AnnealIncumbent:
        """Decode and score one immutable annealing state exactly."""


@dataclass(frozen=True, slots=True)
class PythonSequenceKernel:
    """Authoritative pure-Python implementation of :class:`SequenceKernel`."""

    problem: sequence_pair.PlacementProblem
    context: sequence_pair.PlacementCostContext
    backend: ClassVar[BackendName] = "python"

    def __post_init__(self) -> None:
        _validate_stable_context(self.problem, self.context)

    def score_state(
        self,
        state: sequence_pair.AnnealState,
        *,
        direct_targets: tuple[sequence_pair.DirectInsertTarget, ...] | None = None,
    ) -> sequence_pair.AnnealIncumbent:
        """Use the reference decoder and scorer without changing their validation."""
        return sequence_pair._score_state(
            self.problem,
            state,
            self.context,
            direct_targets=direct_targets,
        )


class CompiledSequenceKernel:
    """Ahead-of-time Cython kernel with candidate-independent buffers cached once."""

    backend: ClassVar[BackendName] = "cython"

    def __init__(
        self,
        problem: sequence_pair.PlacementProblem,
        context: sequence_pair.PlacementCostContext,
    ) -> None:
        if _compiled_decode_score is None:
            raise RuntimeError("the ahead-of-time sequence kernel is unavailable")
        _validate_stable_context(problem, context)
        self.problem = problem
        self.context = context
        self._nets = _integer_buffer(context.net_pairs)
        self._weights = array("d", context.net_weights)
        self._history = array("d", context.history_summed_area)
        self._fixed_sizes: tuple[tuple[tuple[int, int], ...], array[int]] | None = None
        self._sizes: dict[tuple[int, ...], tuple[tuple[tuple[int, int], ...], array[int]]] = {}
        if problem.variant_tables:
            zero_indices = (0,) * problem.size
            zero_sizes = problem.selected_sizes(zero_indices)
            self._sizes[zero_indices] = (zero_sizes, _integer_buffer(zero_sizes))
        else:
            self._fixed_sizes = (problem.sizes, _integer_buffer(problem.sizes))
        self._targets: dict[tuple[sequence_pair.DirectInsertTarget, ...], array[int]] = {
            context.direct_targets: _target_buffer(context.direct_targets)
        }
        size = problem.size
        adjacency_size = size * size
        self._workspace_buffers = (
            array("q", [0]) * size,
            bytearray(adjacency_size),
            bytearray(adjacency_size),
            array("q", [0]) * size,
            array("q", [0]) * size,
            array("q", [0]) * size,
            array("q", [0]) * size,
        )

    def score_state(
        self,
        state: sequence_pair.AnnealState,
        *,
        direct_targets: tuple[sequence_pair.DirectInsertTarget, ...] | None = None,
    ) -> sequence_pair.AnnealIncumbent:
        """Convert candidate-only data and rebuild validated immutable records."""
        state.pair.validate(self.problem.size)
        if len(state.gaps.east) != self.problem.size:
            raise ValueError("annealing state size must match the placement problem")
        sizes, sizes_buffer = self._selected_sizes(state.variant_indices)
        targets = self.context.direct_targets if direct_targets is None else direct_targets
        if not isinstance(targets, tuple) or any(
            not isinstance(target, sequence_pair.DirectInsertTarget) for target in targets
        ):
            raise ValueError("direct-insert targets must be an immutable tuple")
        for target in targets:
            sequence_pair._validate_direct_target(self.problem, target, sizes)
        if targets:
            # The compiled target buffer represents only span overlap. Static
            # access now requires one of the discrete collision-free origin
            # deltas, so direct-aware scoring stays on the authoritative path.
            return sequence_pair._score_state(
                self.problem,
                state,
                self.context,
                direct_targets=targets,
            )
        targets_buffer = self._targets.get(targets)
        if targets_buffer is None:
            targets_buffer = _target_buffer(targets)
            self._targets[targets] = targets_buffer

        compiled_decode_score = _compiled_decode_score
        if compiled_decode_score is None:
            raise RuntimeError("the ahead-of-time sequence kernel is unavailable")
        result = compiled_decode_score(
            array("q", state.pair.positive),
            array("q", state.pair.negative),
            array("q", state.gaps.east),
            array("q", state.gaps.north),
            sizes_buffer,
            self._nets,
            self._weights,
            self._history,
            targets_buffer,
            *self._workspace_buffers,
            self.problem.outline_height,
            self.context.history_outline[0],
            catalog.SORTER_MAX_REACH,
        )
        (
            x_values,
            y_values,
            latest_x_values,
            latest_y_values,
            width,
            used_height,
            gap_area,
            box_area,
            weighted_hpwl,
            history_cost,
            missed_direct_inserts,
            hard_outline_overflow,
        ) = result
        x = tuple(x_values)
        y = tuple(y_values)
        latest_x = tuple(latest_x_values)
        latest_y = tuple(latest_y_values)
        decoded = sequence_pair.DecodedPlacement(
            x=x,
            y=y,
            width=width,
            used_height=used_height,
            x_windows=tuple(zip(x, latest_x, strict=True)),
            y_windows=tuple(zip(y, latest_y, strict=True)),
            gap_area=gap_area,
            variant_indices=state.variant_indices,
        )
        breakdown = sequence_pair.EnergyBreakdown(
            width=width,
            used_height=used_height,
            box_area=box_area,
            gap_area=gap_area,
            weighted_hpwl=weighted_hpwl,
            history_cost=history_cost,
            missed_direct_inserts=missed_direct_inserts,
            hard_outline_overflow=hard_outline_overflow,
            outline_height=self.problem.outline_height,
            area_lower_bound=self.problem.area_lower_bound,
            net_count=len(self.context.net_pairs),
        )
        return sequence_pair.AnnealIncumbent(
            state=state,
            decoded=decoded,
            breakdown=breakdown,
            key=sequence_pair.PlacementKey(
                x=x,
                y=y,
                dimensions=sizes,
                east_gaps=state.gaps.east,
                north_gaps=state.gaps.north,
                instance_ids=self.problem.instance_ids,
                variant_ids=self.problem.selected_variant_ids(state.variant_indices),
            ),
        )

    def _selected_sizes(
        self,
        variant_indices: tuple[int, ...],
    ) -> tuple[tuple[tuple[int, int], ...], array[int]]:
        if self._fixed_sizes is not None:
            self.problem._validate_variant_indices(variant_indices)
            return self._fixed_sizes
        cached = self._sizes.get(variant_indices)
        if cached is None:
            sizes = self.problem.selected_sizes(variant_indices)
            cached = (sizes, _integer_buffer(sizes))
            self._sizes[variant_indices] = cached
        return cached


def compiled_backend_available() -> bool:
    """Return whether the installed package contains the prebuilt extension."""
    return _compiled_decode_score is not None


def build_sequence_kernel(
    problem: sequence_pair.PlacementProblem,
    context: sequence_pair.PlacementCostContext,
) -> SequenceKernel:
    """Select the compiled backend only when its fixed-width domain is exact."""
    if compiled_backend_available() and _compiled_inputs_are_safe(problem, context):
        return CompiledSequenceKernel(problem, context)
    return PythonSequenceKernel(problem, context)


def _compiled_inputs_are_safe(
    problem: sequence_pair.PlacementProblem,
    context: sequence_pair.PlacementCostContext,
) -> bool:
    if context.direct_targets:
        return False
    if any(type(value) is not float for value in context.net_weights):
        return False
    if any(type(value) is not float for value in context.history_summed_area):
        return False

    size = problem.size
    history_width, history_height = context.history_outline
    workspace_products = (
        size * size,
        size * 2,
        len(context.net_pairs) * 2,
        len(context.direct_targets) * 6,
        (history_width + 1) * (history_height + 1),
    )
    if any(product > _BUFFER_INDEX_MAX for product in workspace_products):
        return False
    if problem.outline_height > _SIGNED_64_MAX or history_width > _SIGNED_64_MAX:
        return False
    if any(
        value > _SIGNED_64_MAX
        for target in context.direct_targets
        for value in (
            target.producer,
            target.consumer,
            target.producer_row,
            target.consumer_row,
            target.producer_span,
            target.consumer_span,
        )
    ):
        return False

    dimensions = _conservative_dimensions(problem)
    horizontal_span = sum(width + sequence_pair._MAX_GAP for width, _height in dimensions)
    vertical_span = sum(height + sequence_pair._MAX_GAP for _width, height in dimensions)
    geometry_intermediates = (
        horizontal_span,
        vertical_span,
        horizontal_span + vertical_span,
        sum(width * height for width, height in dimensions),
        sequence_pair._MAX_GAP * sum(width + height for width, height in dimensions),
    )
    return all(value <= _SIGNED_64_MAX for value in geometry_intermediates)


def _conservative_dimensions(
    problem: sequence_pair.PlacementProblem,
) -> tuple[tuple[int, int], ...]:
    if not problem.variant_tables:
        return problem.sizes
    dimensions: list[tuple[int, int]] = []
    for strip, variants in enumerate(problem.variant_tables):
        default = variants[0]
        base_width, base_height = problem.sizes[strip]
        dimensions.append(
            (
                max(variant.box_width + base_width - default.box_width for variant in variants),
                max(variant.box_height + base_height - default.box_height for variant in variants),
            )
        )
    return tuple(dimensions)


def _validate_stable_context(
    problem: sequence_pair.PlacementProblem,
    context: sequence_pair.PlacementCostContext,
) -> None:
    if context.net_pairs != problem.nets:
        raise ValueError("placement cost context must match the problem net identities")
    if context.history_outline[1] != problem.outline_height:
        raise ValueError("placement cost context must match the problem outline height")


def _integer_buffer(rows: tuple[tuple[int, ...], ...]) -> array[int]:
    values = array("q")
    for row in rows:
        values.extend(row)
    return values


def _target_buffer(targets: tuple[sequence_pair.DirectInsertTarget, ...]) -> array[int]:
    values = array("q")
    for target in targets:
        values.extend(
            (
                target.producer,
                target.consumer,
                target.producer_row,
                target.consumer_row,
                target.producer_span,
                target.consumer_span,
            )
        )
    return values
