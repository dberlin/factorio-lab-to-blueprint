"""Exact decode-and-score backends for sequence-pair annealing."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol, runtime_checkable

import flab2bp.layout.sequence_pair as sequence_pair
from flab2bp.dsp import catalog

try:
    from flab2bp.layout._sequence_kernel import decode_score as _compiled_decode_score
except ImportError:
    _compiled_decode_score = None

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
        self._sizes: dict[
            tuple[int, ...], tuple[tuple[tuple[int, int], ...], array[int]]
        ] = {}
        if problem.variant_tables:
            zero_indices = (0,) * problem.size
            zero_sizes = problem.selected_sizes(zero_indices)
            self._sizes[zero_indices] = (zero_sizes, _integer_buffer(zero_sizes))
        else:
            self._fixed_sizes = (problem.sizes, _integer_buffer(problem.sizes))
        self._targets: dict[tuple[sequence_pair.DirectInsertTarget, ...], array[int]] = {
            context.direct_targets: _target_buffer(context.direct_targets)
        }

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
    """Select the compiled backend when installed, otherwise the Python reference."""
    if compiled_backend_available():
        return CompiledSequenceKernel(problem, context)
    return PythonSequenceKernel(problem, context)


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
