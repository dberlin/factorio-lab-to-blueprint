"""Deterministic fixed-orientation sequence-pair placement."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING

from flab2bp.dsp import catalog

if TYPE_CHECKING:
    from flab2bp.layout.route_feedback import LogicalNetId
    from flab2bp.layout.strip_variants import (
        StripFamily,
        StripInstanceId,
        StripVariant,
        StripVariantId,
    )

_MAX_GAP = 4


@dataclass(frozen=True, slots=True)
class SequencePair:
    """Two permutations whose pairwise orders define rectangle relations."""

    positive: tuple[int, ...]
    negative: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.positive, tuple) or not isinstance(self.negative, tuple):
            raise ValueError("sequence-pair permutations must be immutable tuples")
        self.validate(len(self.positive))

    def validate(self, size: int) -> None:
        """Raise when either permutation is not exactly ``range(size)``."""
        if type(size) is not int or size < 0:
            raise ValueError("sequence-pair size must be a non-negative integer")
        wanted = tuple(range(size))
        if (
            not all(type(strip) is int for strip in self.positive + self.negative)
            or tuple(sorted(self.positive)) != wanted
            or tuple(sorted(self.negative)) != wanted
        ):
            raise ValueError(
                "both sequence-pair permutations must contain every strip exactly once"
            )


@dataclass(frozen=True, slots=True)
class GapProfile:
    """Bounded whitespace attached to each strip's east and north sides."""

    east: tuple[int, ...]
    north: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.east, tuple) or not isinstance(self.north, tuple):
            raise ValueError("gap profiles must be immutable tuples")
        if len(self.east) != len(self.north):
            raise ValueError("east and north gap profiles must have the same size")
        if not all(type(gap) is int and 0 <= gap <= _MAX_GAP for gap in self.east + self.north):
            raise ValueError(f"gap values must be integers from 0 to {_MAX_GAP}")

    @classmethod
    def zero(cls, size: int) -> GapProfile:
        """Return a profile with no explicit whitespace."""
        if type(size) is not int or size < 0:
            raise ValueError("gap profile size must be a non-negative integer")
        return cls((0,) * size, (0,) * size)


@dataclass(frozen=True, slots=True)
class PlacementProblem:
    """Fixed strip identities, pose variants, and net endpoints for placement search."""

    sizes: tuple[tuple[int, int], ...]
    nets: tuple[tuple[int, int], ...]
    outline_height: int
    area_lower_bound: int
    instance_ids: tuple[StripInstanceId, ...] = ()
    logical_net_ids: tuple[LogicalNetId, ...] = ()
    variant_tables: tuple[tuple[StripVariant, ...], ...] = ()

    def __post_init__(self) -> None:
        _validate_sizes(self.sizes)
        if not isinstance(self.nets, tuple):
            raise ValueError("nets must be an immutable tuple")
        size = len(self.sizes)
        if any(
            not isinstance(net, tuple)
            or len(net) != 2
            or any(type(strip) is not int or not 0 <= strip < size for strip in net)
            for net in self.nets
        ):
            raise ValueError("net endpoints must identify strips in the placement problem")
        _validate_positive_integer(self.outline_height, "outline height")
        if type(self.area_lower_bound) is not int or self.area_lower_bound < 0:
            raise ValueError("area lower bound must be a non-negative integer")
        if not isinstance(self.instance_ids, tuple) or not isinstance(self.variant_tables, tuple):
            raise ValueError("strip instances and variant tables must be immutable tuples")
        if bool(self.instance_ids) != bool(self.variant_tables):
            raise ValueError("strip instances and variant tables must be supplied together")
        if self.variant_tables:
            if len(self.instance_ids) != size or len(self.variant_tables) != size:
                raise ValueError("variant-aware problems require one instance and table per strip")
            for strip, (instance_id, variants) in enumerate(
                zip(self.instance_ids, self.variant_tables, strict=True)
            ):
                if not isinstance(variants, tuple) or not variants:
                    raise ValueError("every strip variant table must be a non-empty tuple")
                if any(
                    variant.variant_id.family_id != instance_id.family_id
                    or len(variant.machine_origins_x) != instance_id.machine_count
                    for variant in variants
                ):
                    raise ValueError("strip variants must realize the exact owning instance")
                if (
                    self.sizes[strip][0] < variants[0].box_width
                    or self.sizes[strip][1] < variants[0].box_height
                ):
                    raise ValueError("problem default sizes must contain variant index zero")
        if not isinstance(self.logical_net_ids, tuple) or (
            self.logical_net_ids and len(self.logical_net_ids) != len(self.nets)
        ):
            raise ValueError("logical net ids must match the immutable placement nets")
        if self.instance_ids and self.logical_net_ids:
            expected_families = tuple(
                (
                    self.instance_ids[source].family_id,
                    self.instance_ids[destination].family_id,
                )
                for source, destination in self.nets
            )
            actual_families = tuple(
                (logical.source_family, logical.destination_family)
                for logical in self.logical_net_ids
            )
            if actual_families != expected_families:
                raise ValueError("logical net ids must match current physical endpoints")

    @property
    def size(self) -> int:
        return len(self.sizes)

    def variant(self, strip: int, variant: int) -> StripVariant:
        """Return one exact pose variant after validating both indices."""
        if type(strip) is not int or not 0 <= strip < self.size:
            raise ValueError("strip index must identify a placement strip")
        if not self.variant_tables:
            raise ValueError("the placement problem has no strip variant tables")
        table = self.variant_tables[strip]
        if type(variant) is not int or not 0 <= variant < len(table):
            raise ValueError("variant index must identify a pose-valid strip variant")
        return table[variant]

    def selected_sizes(self, variant_indices: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
        """Return box dimensions for one complete immutable selection."""
        indices = self._validate_variant_indices(variant_indices)
        if not self.variant_tables:
            return self.sizes
        selected: list[tuple[int, int]] = []
        for strip, variant_index in enumerate(indices):
            default = self.variant_tables[strip][0]
            variant = self.variant(strip, variant_index)
            selected.append(
                (
                    variant.box_width + self.sizes[strip][0] - default.box_width,
                    variant.box_height + self.sizes[strip][1] - default.box_height,
                )
            )
        return tuple(selected)

    def selected_variant_ids(self, variant_indices: tuple[int, ...]) -> tuple[StripVariantId, ...]:
        """Return the exact physical identities in one complete selection."""
        indices = self._validate_variant_indices(variant_indices)
        if not self.variant_tables:
            return ()
        return tuple(
            self.variant(strip, variant).variant_id for strip, variant in enumerate(indices)
        )

    def _validate_variant_indices(self, variant_indices: tuple[int, ...]) -> tuple[int, ...]:
        if not isinstance(variant_indices, tuple):
            raise ValueError("variant indices must be an immutable tuple")
        if not self.variant_tables and not variant_indices:
            return ()
        if len(variant_indices) != self.size:
            raise ValueError("selection must contain one variant index per strip")
        if self.variant_tables:
            for strip, variant in enumerate(variant_indices):
                self.variant(strip, variant)
        elif any(type(variant) is not int or variant != 0 for variant in variant_indices):
            raise ValueError("fixed-size strips only accept variant index zero")
        return variant_indices


@dataclass(frozen=True, slots=True)
class DirectInsertTarget:
    """Immutable strip geometry for one direct-insertion opportunity."""

    key: tuple[int, int]
    producer: int
    consumer: int
    producer_row: int
    consumer_row: int
    producer_span: int
    consumer_span: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.key, tuple)
            or len(self.key) != 2
            or any(type(part) is not int or part < 0 for part in self.key)
        ):
            raise ValueError("direct-insert key must contain two non-negative integers")
        if any(
            type(value) is not int or value < 0
            for value in (
                self.producer,
                self.consumer,
                self.producer_row,
                self.consumer_row,
            )
        ):
            raise ValueError("direct-insert indices and rows must be non-negative integers")
        if self.producer == self.consumer:
            raise ValueError("direct insert must connect distinct strips")
        _validate_positive_integer(self.producer_span, "producer span")
        _validate_positive_integer(self.consumer_span, "consumer span")


@dataclass(frozen=True, slots=True)
class DecodedPlacement:
    """Placed coordinates, their legal windows, and realized direct inserts."""

    x: tuple[int, ...]
    y: tuple[int, ...]
    width: int
    used_height: int
    x_windows: tuple[tuple[int, int], ...]
    y_windows: tuple[tuple[int, int], ...]
    gap_area: int
    direct: frozenset[tuple[int, int]] = frozenset()
    variant_indices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            isinstance(values, tuple) for values in (self.x, self.y, self.x_windows, self.y_windows)
        ):
            raise ValueError("decoded coordinates and windows must be immutable tuples")
        size = len(self.x)
        if len(self.y) != size or len(self.x_windows) != size or len(self.y_windows) != size:
            raise ValueError("decoded coordinates and windows must have the same size")
        if not all(type(coordinate) is int and coordinate >= 0 for coordinate in self.x + self.y):
            raise ValueError("decoded coordinates must be non-negative integers")
        if any(
            not isinstance(window, tuple)
            or len(window) != 2
            or any(type(coordinate) is not int for coordinate in window)
            for window in self.x_windows + self.y_windows
        ):
            raise ValueError("coordinate windows must contain integer pairs")
        for coordinate, window, name in (
            *((value, bounds, "x") for value, bounds in zip(self.x, self.x_windows, strict=True)),
            *((value, bounds, "y") for value, bounds in zip(self.y, self.y_windows, strict=True)),
        ):
            earliest, latest = window
            if (
                coordinate < earliest
                or (earliest <= latest and coordinate > latest)
                or (earliest > latest and coordinate != earliest)
            ):
                raise ValueError(f"decoded {name} coordinate must lie inside its legal window")
        if not isinstance(self.direct, frozenset) or any(
            not isinstance(key, tuple)
            or len(key) != 2
            or any(type(part) is not int or part < 0 for part in key)
            for key in self.direct
        ):
            raise ValueError("realized direct inserts must be an immutable set of integer pairs")
        if (
            not isinstance(self.variant_indices, tuple)
            or (self.variant_indices and len(self.variant_indices) != size)
            or any(type(variant) is not int or variant < 0 for variant in self.variant_indices)
        ):
            raise ValueError(
                "decoded placement must carry one non-negative variant index per strip"
            )
        for value, name in (
            (self.width, "decoded width"),
            (self.used_height, "decoded used height"),
            (self.gap_area, "decoded gap area"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


class MoveKind(Enum):
    """Legal local mutations of a sequence-pair annealing state."""

    SWAP_POSITIVE = "swap_positive"
    SWAP_NEGATIVE = "swap_negative"
    SWAP_BOTH = "swap_both"
    INSERT_POSITIVE = "insert_positive"
    INSERT_NEGATIVE = "insert_negative"
    GAP_STEP = "gap_step"
    CHANGE_VARIANT = "change_variant"


class EliteCategory(Enum):
    """Deterministic reason an annealing incumbent belongs in the elite archive."""

    BLENDED = "blended"
    NARROWEST = "narrowest"
    LOWEST_HPWL = "lowest_hpwl"
    LOWEST_HISTORY = "lowest_history"


@dataclass(frozen=True, slots=True)
class AnnealConfig:
    """Fixed schedule for one deterministic annealing temperature stage."""

    moves_per_stage: int = 2_000
    initial_temperature: float = 1.0
    final_temperature: float = 0.01
    elite_count: int = 8

    def __post_init__(self) -> None:
        if type(self.moves_per_stage) is not int or self.moves_per_stage <= 0:
            raise ValueError("moves per stage must be a positive integer")
        if (
            not math.isfinite(self.initial_temperature)
            or self.initial_temperature <= 0.0
            or not math.isfinite(self.final_temperature)
            or self.final_temperature <= 0.0
            or self.initial_temperature < self.final_temperature
        ):
            raise ValueError("temperatures must be finite, positive, and non-increasing")
        if type(self.elite_count) is not int or self.elite_count <= 0:
            raise ValueError("elite count must be a positive integer")

    @classmethod
    def test(cls) -> AnnealConfig:
        """Return a small deterministic schedule for focused tests."""
        return cls(
            moves_per_stage=64,
            initial_temperature=1.0,
            final_temperature=0.05,
            elite_count=4,
        )


@dataclass(frozen=True, slots=True)
class PlacementCostContext:
    """Candidate-independent inputs used by cheap placement scoring."""

    net_weights: tuple[float, ...]
    net_pairs: tuple[tuple[int, int], ...]
    history_outline: tuple[int, int]
    history_summed_area: tuple[float, ...]
    direct_targets: tuple[DirectInsertTarget, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.net_weights, tuple) or any(
            not math.isfinite(value) or value < 0.0 for value in self.net_weights
        ):
            raise ValueError("placement net weights must be a finite non-negative tuple")
        if not isinstance(self.net_pairs, tuple) or any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or any(type(endpoint) is not int or endpoint < 0 for endpoint in pair)
            for pair in self.net_pairs
        ):
            raise ValueError("placement net pairs must contain non-negative integer endpoints")
        if len(self.net_weights) != len(self.net_pairs):
            raise ValueError("placement net weights must match the logical net pairs")
        if (
            not isinstance(self.history_outline, tuple)
            or len(self.history_outline) != 2
            or any(type(value) is not int or value < 0 for value in self.history_outline)
        ):
            raise ValueError("history outline must contain non-negative integer dimensions")
        width, height = self.history_outline
        if (
            not isinstance(self.history_summed_area, tuple)
            or len(self.history_summed_area) != (width + 1) * (height + 1)
            or any(not math.isfinite(value) or value < 0.0 for value in self.history_summed_area)
        ):
            raise ValueError(
                "history summed-area data must be finite, non-negative, and match its outline"
            )
        if not isinstance(self.direct_targets, tuple) or any(
            not isinstance(target, DirectInsertTarget) for target in self.direct_targets
        ):
            raise ValueError("direct-insert targets must be an immutable tuple")


@dataclass(frozen=True, order=True, slots=True)
class SearchEnergy:
    """Lexicographic cheap objective with outline overflow ordered first."""

    hard_outline_overflow: int
    scalar: float

    @classmethod
    def from_breakdown(cls, breakdown: EnergyBreakdown) -> SearchEnergy:
        """Derive the blended objective from one raw candidate observation."""
        area_scale = max(breakdown.area_lower_bound, 1)
        net_scale = max(breakdown.net_count, 1)
        return cls(
            hard_outline_overflow=breakdown.hard_outline_overflow,
            scalar=(
                breakdown.width * breakdown.outline_height / area_scale
                + 0.35 * breakdown.weighted_hpwl / area_scale
                + 0.2 * breakdown.history_cost / net_scale
                + 0.1 * breakdown.missed_direct_inserts / net_scale
                + 0.05 * breakdown.gap_area / area_scale
            ),
        )


@dataclass(frozen=True, slots=True)
class EnergyBreakdown:
    """Immutable raw geometry and routing-proxy metrics for one candidate."""

    width: int
    used_height: int
    box_area: int
    gap_area: int
    weighted_hpwl: float
    history_cost: float
    missed_direct_inserts: int
    hard_outline_overflow: int
    outline_height: int
    area_lower_bound: int
    net_count: int
    energy: SearchEnergy = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "energy", SearchEnergy.from_breakdown(self))


@dataclass(frozen=True, slots=True)
class AnnealState:
    """Immutable sequence-pair, variant selection, and deterministic stage seed."""

    pair: SequencePair
    gaps: GapProfile
    base_seed: int
    stage_index: int = 0
    variant_indices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        size = len(self.pair.positive)
        if len(self.gaps.east) != size:
            raise ValueError("annealing pair and gap profile sizes must match")
        if (
            not isinstance(self.variant_indices, tuple)
            or (self.variant_indices and len(self.variant_indices) != size)
            or any(type(variant) is not int or variant < 0 for variant in self.variant_indices)
        ):
            raise ValueError(
                "annealing state must carry one variant index per strip, all non-negative"
            )
        if type(self.base_seed) is not int:
            raise ValueError("annealing base seed must be an integer")
        if type(self.stage_index) is not int or self.stage_index < 0:
            raise ValueError("annealing stage index must be a non-negative integer")

    @classmethod
    def initial(cls, size: int, seed: int) -> AnnealState:
        """Create a reproducible independently shuffled fixed-cardinality start."""
        if type(size) is not int or size < 0:
            raise ValueError("annealing state size must be a non-negative integer")
        if type(seed) is not int:
            raise ValueError("annealing seed must be an integer")
        rng = random.Random(seed)
        positive = list(range(size))
        negative = list(range(size))
        rng.shuffle(positive)
        rng.shuffle(negative)
        return cls(
            pair=SequencePair(tuple(positive), tuple(negative)),
            gaps=GapProfile.zero(size),
            base_seed=seed,
            variant_indices=(0,) * size,
        )


@dataclass(frozen=True, slots=True)
class StageBoundaryUpdate:
    """A complete fixed-cardinality problem/state rebuilt between SA stages."""

    problem: PlacementProblem
    state: AnnealState

    def __post_init__(self) -> None:
        if self.problem.size != len(self.state.pair.positive):
            raise ValueError("stage-boundary problem and state cardinality disagree")
        self.problem._validate_variant_indices(self.state.variant_indices)


@dataclass(frozen=True, order=True, slots=True)
class PlacementKey:
    """Exact instance, variant, and geometry identity retained by search."""

    x: tuple[int, ...]
    y: tuple[int, ...]
    dimensions: tuple[tuple[int, int], ...]
    east_gaps: tuple[int, ...]
    north_gaps: tuple[int, ...]
    instance_ids: tuple[StripInstanceId, ...] = ()
    variant_ids: tuple[StripVariantId, ...] = ()


@dataclass(frozen=True, slots=True)
class AnnealIncumbent:
    """Scored annealing state retained at a stage boundary."""

    state: AnnealState
    decoded: DecodedPlacement
    breakdown: EnergyBreakdown
    key: PlacementKey

    @property
    def energy(self) -> SearchEnergy:
        """Return the objective derived from this incumbent's sole score source."""
        return self.breakdown.energy


@dataclass(frozen=True, slots=True)
class TaggedAnnealIncumbent:
    """One exact incumbent with its ordered elite-category memberships."""

    incumbent: AnnealIncumbent
    categories: tuple[EliteCategory, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.categories, tuple)
            or not self.categories
            or len(set(self.categories)) != len(self.categories)
            or self.categories
            != tuple(category for category in EliteCategory if category in self.categories)
        ):
            raise ValueError("elite categories must be a non-empty canonical tuple")


@dataclass(frozen=True, slots=True, init=False)
class AnnealStageResult:
    """Result of exactly one deterministic temperature stage."""

    final_state: AnnealState
    incumbent: AnnealIncumbent
    accepted_moves: int
    archive: tuple[TaggedAnnealIncumbent, ...]

    def __init__(
        self,
        final_state: AnnealState,
        incumbent: AnnealIncumbent,
        accepted_moves: int,
        elites: tuple[AnnealIncumbent, ...] | None = None,
        *,
        archive: tuple[TaggedAnnealIncumbent, ...] | None = None,
    ) -> None:
        """Build a tagged result while accepting the legacy untagged elite argument."""
        if archive is None:
            if elites is None:
                raise TypeError("annealing stage result requires an elite archive")
            archive = tuple(
                TaggedAnnealIncumbent(elite, (EliteCategory.BLENDED,)) for elite in elites
            )
        elif elites is not None and elites != tuple(entry.incumbent for entry in archive):
            raise ValueError("tagged archive and compatibility elites must agree")
        object.__setattr__(self, "final_state", final_state)
        object.__setattr__(self, "incumbent", incumbent)
        object.__setattr__(self, "accepted_moves", accepted_moves)
        object.__setattr__(self, "archive", archive)

    @property
    def elites(self) -> tuple[AnnealIncumbent, ...]:
        """Return the archive incumbents for compatibility with existing consumers."""
        return tuple(entry.incumbent for entry in self.archive)


def decode_sequence_pair(
    pair: SequencePair,
    gaps: GapProfile,
    sizes: tuple[tuple[int, int], ...],
    *,
    outline_height: int,
    outline_width: int | None = None,
) -> DecodedPlacement:
    """Return earliest legal coordinates and latest shifts inside the outline.

    An outline smaller than the compacted placement is retained as an infeasible
    window (latest less than earliest), allowing search to score the overflow.
    """
    _validate_sizes(sizes)
    size = len(sizes)
    pair.validate(size)
    if len(gaps.east) != size:
        raise ValueError("gap profile size must match the rectangle count")
    _validate_positive_integer(outline_height, "outline height")
    if outline_width is not None:
        _validate_positive_integer(outline_width, "outline width")

    negative_position = [0] * size
    for position, strip in enumerate(pair.negative):
        negative_position[strip] = position

    horizontal: list[list[int]] = [[] for _ in range(size)]
    vertical: list[list[int]] = [[] for _ in range(size)]
    for first_position, first in enumerate(pair.positive):
        for second in pair.positive[first_position + 1 :]:
            if negative_position[first] < negative_position[second]:
                horizontal[first].append(second)
            else:
                vertical[second].append(first)

    widths = tuple(width for width, _height in sizes)
    heights = tuple(height for _width, height in sizes)
    horizontal_order = pair.positive
    vertical_order = tuple(reversed(pair.positive))
    earliest_x = _earliest_coordinates(horizontal, horizontal_order, widths, gaps.east)
    earliest_y = _earliest_coordinates(vertical, vertical_order, heights, gaps.north)

    width = max((earliest_x[index] + widths[index] for index in range(size)), default=0)
    used_height = max((earliest_y[index] + heights[index] for index in range(size)), default=0)
    latest_x = _latest_coordinates(
        horizontal,
        horizontal_order,
        widths,
        gaps.east,
        outline_width if outline_width is not None else width,
    )
    latest_y = _latest_coordinates(
        vertical,
        vertical_order,
        heights,
        gaps.north,
        outline_height,
    )
    gap_area = sum(
        gaps.east[index] * heights[index] + gaps.north[index] * widths[index]
        for index in range(size)
    )

    return DecodedPlacement(
        x=earliest_x,
        y=earliest_y,
        width=width,
        used_height=used_height,
        x_windows=tuple(zip(earliest_x, latest_x, strict=True)),
        y_windows=tuple(zip(earliest_y, latest_y, strict=True)),
        gap_area=gap_area,
    )


def decode_state(problem: PlacementProblem, state: AnnealState) -> DecodedPlacement:
    """Decode one complete pose selection using only its selected box geometry."""
    state.pair.validate(problem.size)
    if len(state.gaps.east) != problem.size:
        raise ValueError("annealing state size must match the placement problem")
    sizes = problem.selected_sizes(state.variant_indices)
    decoded = decode_sequence_pair(
        state.pair,
        state.gaps,
        sizes,
        outline_height=problem.outline_height,
    )
    return DecodedPlacement(
        x=decoded.x,
        y=decoded.y,
        width=decoded.width,
        used_height=decoded.used_height,
        x_windows=decoded.x_windows,
        y_windows=decoded.y_windows,
        gap_area=decoded.gap_area,
        direct=decoded.direct,
        variant_indices=state.variant_indices,
    )


def align_direct_inserts(
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    targets: tuple[DirectInsertTarget, ...],
) -> DecodedPlacement:
    """Realize direct inserts by deterministic shifts inside decoded windows."""
    if not isinstance(targets, tuple):
        raise ValueError("direct-insert targets must be an immutable tuple")
    if len(decoded.x) != problem.size:
        raise ValueError("decoded placement size must match the placement problem")
    sizes = problem.selected_sizes(decoded.variant_indices)

    current = decoded
    targets_by_key: dict[tuple[int, int], list[DirectInsertTarget]] = {}
    for target in targets:
        targets_by_key.setdefault(target.key, []).append(target)
    carried_targets: dict[tuple[int, int], DirectInsertTarget] = {}
    for key in sorted(decoded.direct):
        matching = targets_by_key.get(key, [])
        if not matching:
            raise ValueError(f"target geometry is required for carried direct key {key}")
        if len(matching) > 1:
            raise ValueError(f"duplicate carried direct target geometry for key {key}")
        carried = matching[0]
        _validate_direct_target(problem, carried, sizes)
        if not _target_is_direct(decoded, carried):
            raise ValueError(f"carried direct target geometry is not realized for key {key}")
        carried_targets[key] = carried

    # Every target replaces one belt net, so benefit is equal; the immutable
    # geometry tuple is the stable tie-break independent of caller iteration.
    ordered = sorted(
        targets,
        key=lambda target: (
            target.key,
            target.producer,
            target.consumer,
            target.producer_row,
            target.consumer_row,
            target.producer_span,
            target.consumer_span,
        ),
    )
    realized_targets = carried_targets.copy()
    for target in ordered:
        _validate_direct_target(problem, target, sizes)
        if target.key in current.direct:
            continue
        candidate = _align_direct_target(
            current,
            target,
            sizes,
            outline=(decoded.width, decoded.used_height),
        )
        if candidate is None:
            continue
        if not _preserves_separations(decoded, candidate, sizes):
            continue
        if not all(
            _target_is_direct(candidate, accepted)
            for accepted in (*realized_targets.values(), target)
        ):
            continue
        current = candidate
        realized_targets[target.key] = target
    return current


def _validate_direct_target(
    problem: PlacementProblem,
    target: DirectInsertTarget,
    sizes: tuple[tuple[int, int], ...],
) -> None:
    if len(sizes) != problem.size:
        raise ValueError("selected strip sizes must match the placement problem")
    if not 0 <= target.producer < problem.size or not 0 <= target.consumer < problem.size:
        raise ValueError("direct-insert target endpoints must identify placement strips")
    producer_size = sizes[target.producer]
    consumer_size = sizes[target.consumer]
    if (
        target.producer_row >= producer_size[1]
        or target.consumer_row >= consumer_size[1]
        or target.producer_span > producer_size[0]
        or target.consumer_span > consumer_size[0]
    ):
        raise ValueError("direct-insert target geometry must lie inside its endpoint strips")


def _align_direct_target(
    decoded: DecodedPlacement,
    target: DirectInsertTarget,
    sizes: tuple[tuple[int, int], ...],
    *,
    outline: tuple[int, int],
) -> DecodedPlacement | None:
    producer = target.producer
    consumer = target.consumer
    producer_width, producer_height = sizes[producer]
    consumer_width, consumer_height = sizes[consumer]

    producer_x_bounds = _relation_bounds(decoded, sizes, producer, consumer, axis=0)
    consumer_x_bounds = _relation_bounds(decoded, sizes, consumer, producer, axis=0)
    producer_y_bounds = _relation_bounds(decoded, sizes, producer, consumer, axis=1)
    consumer_y_bounds = _relation_bounds(decoded, sizes, consumer, producer, axis=1)

    x_difference = [-(target.consumer_span - 1), target.producer_span - 1]
    y_difference = [
        1 + target.producer_row - target.consumer_row,
        catalog.SORTER_MAX_REACH + target.producer_row - target.consumer_row,
    ]
    _preserve_pair_relation(
        decoded.x[producer],
        producer_width,
        decoded.x[consumer],
        consumer_width,
        x_difference,
    )
    _preserve_pair_relation(
        decoded.y[producer],
        producer_height,
        decoded.y[consumer],
        consumer_height,
        y_difference,
    )
    x_pair = _closest_coordinate_pair(
        decoded.x[producer],
        producer_x_bounds,
        decoded.x[consumer],
        consumer_x_bounds,
        x_difference,
    )
    y_pair = _closest_coordinate_pair(
        decoded.y[producer],
        producer_y_bounds,
        decoded.y[consumer],
        consumer_y_bounds,
        y_difference,
    )
    if x_pair is None or y_pair is None:
        return None

    x = list(decoded.x)
    y = list(decoded.y)
    x[producer], x[consumer] = x_pair
    y[producer], y[consumer] = y_pair
    width = max(coordinate + size[0] for coordinate, size in zip(x, sizes, strict=True))
    used_height = max(coordinate + size[1] for coordinate, size in zip(y, sizes, strict=True))
    if width > outline[0] or used_height > outline[1]:
        return None

    candidate = DecodedPlacement(
        x=tuple(x),
        y=tuple(y),
        width=width,
        used_height=used_height,
        x_windows=decoded.x_windows,
        y_windows=decoded.y_windows,
        gap_area=decoded.gap_area,
        direct=decoded.direct | {target.key},
        variant_indices=decoded.variant_indices,
    )
    if not _no_overlaps(candidate, sizes):
        return None
    return candidate


def _relation_bounds(
    decoded: DecodedPlacement,
    sizes: tuple[tuple[int, int], ...],
    moving: int,
    other_moving: int,
    *,
    axis: int,
) -> tuple[int, int]:
    coordinates = decoded.x if axis == 0 else decoded.y
    windows = decoded.x_windows if axis == 0 else decoded.y_windows
    lower, upper = windows[moving]
    moving_span = sizes[moving][axis]
    for other, (coordinate, size) in enumerate(zip(coordinates, sizes, strict=True)):
        if other in (moving, other_moving):
            continue
        other_span = size[axis]
        if coordinates[moving] + moving_span <= coordinate:
            upper = min(upper, coordinate - moving_span)
        if coordinate + other_span <= coordinates[moving]:
            lower = max(lower, coordinate + other_span)
    return lower, upper


def _preserve_pair_relation(
    first_coordinate: int,
    first_span: int,
    second_coordinate: int,
    second_span: int,
    difference: list[int],
) -> None:
    if first_coordinate + first_span <= second_coordinate:
        difference[0] = max(difference[0], first_span)
    if second_coordinate + second_span <= first_coordinate:
        difference[1] = min(difference[1], -second_span)


def _closest_coordinate_pair(
    first: int,
    first_bounds: tuple[int, int],
    second: int,
    second_bounds: tuple[int, int],
    difference: list[int],
) -> tuple[int, int] | None:
    difference_low, difference_high = difference
    first_low = max(first_bounds[0], second_bounds[0] - difference_high)
    first_high = min(first_bounds[1], second_bounds[1] - difference_low)
    if first_low > first_high or difference_low > difference_high:
        return None

    breakpoints = (
        first_low,
        first_high,
        first,
        second_bounds[0] - difference_low,
        second_bounds[1] - difference_high,
        second - difference_low,
        second - difference_high,
    )
    candidates: list[tuple[int, int, int]] = []
    for breakpoint in breakpoints:
        first_candidate = min(first_high, max(first_low, breakpoint))
        second_low = max(second_bounds[0], first_candidate + difference_low)
        second_high = min(second_bounds[1], first_candidate + difference_high)
        second_candidate = min(second_high, max(second_low, second))
        candidates.append(
            (
                abs(first_candidate - first) + abs(second_candidate - second),
                first_candidate,
                second_candidate,
            )
        )
    _, chosen_first, chosen_second = min(candidates)
    return chosen_first, chosen_second


def _preserves_separations(
    original: DecodedPlacement,
    candidate: DecodedPlacement,
    sizes: tuple[tuple[int, int], ...],
) -> bool:
    original_boxes = _placement_boxes(original, sizes)
    candidate_boxes = _placement_boxes(candidate, sizes)
    for first in range(len(sizes)):
        for second in range(first + 1, len(sizes)):
            original_separations = _box_separations(original_boxes[first], original_boxes[second])
            candidate_separations = _box_separations(
                candidate_boxes[first], candidate_boxes[second]
            )
            if any(
                was_separate and not remains_separate
                for was_separate, remains_separate in zip(
                    original_separations, candidate_separations, strict=True
                )
            ):
                return False
    return True


def _no_overlaps(decoded: DecodedPlacement, sizes: tuple[tuple[int, int], ...]) -> bool:
    boxes = _placement_boxes(decoded, sizes)
    return all(
        any(_box_separations(boxes[first], boxes[second]))
        for first in range(len(sizes))
        for second in range(first + 1, len(sizes))
    )


def _placement_boxes(
    decoded: DecodedPlacement, sizes: tuple[tuple[int, int], ...]
) -> tuple[tuple[int, int, int, int], ...]:
    return tuple(
        (x, y, x + width, y + height)
        for x, y, (width, height) in zip(decoded.x, decoded.y, sizes, strict=True)
    )


def _box_separations(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> tuple[bool, bool, bool, bool]:
    return (
        first[2] <= second[0],
        second[2] <= first[0],
        first[3] <= second[1],
        second[3] <= first[1],
    )


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


def derive_stage_seed(base_seed: int, stage_index: int) -> int:
    """Derive a stable 64-bit random seed for one multi-start stage."""
    if type(base_seed) is not int:
        raise ValueError("base seed must be an integer")
    if type(stage_index) is not int or stage_index < 0:
        raise ValueError("stage index must be a non-negative integer")
    mask = (1 << 64) - 1
    value = ((base_seed & mask) + 0x9E3779B97F4A7C15 * (stage_index + 1)) & mask
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & mask
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & mask
    return value ^ (value >> 31)


def apply_variant_move(
    problem: PlacementProblem,
    state: AnnealState,
    *,
    strip: int,
    variant: int,
) -> AnnealState:
    """Atomically select one exact pose, box, lane, and attachment plan."""
    problem.selected_sizes(state.variant_indices)
    problem.variant(strip, variant)
    if state.variant_indices[strip] == variant:
        return state
    selected = list(state.variant_indices)
    selected[strip] = variant
    return AnnealState(
        pair=state.pair,
        gaps=state.gaps,
        base_seed=state.base_seed,
        stage_index=state.stage_index,
        variant_indices=tuple(selected),
    )


def apply_move(
    state: AnnealState,
    kind: MoveKind,
    rng: random.Random,
    *,
    problem: PlacementProblem | None = None,
) -> AnnealState:
    """Apply one legal local move while preserving immutable state ownership."""
    if not isinstance(kind, MoveKind):
        raise ValueError("unknown annealing move kind")
    size = len(state.pair.positive)
    if size == 0 or (size == 1 and kind not in (MoveKind.GAP_STEP, MoveKind.CHANGE_VARIANT)):
        return state

    positive = state.pair.positive
    negative = state.pair.negative
    gaps = state.gaps
    if kind is MoveKind.SWAP_POSITIVE:
        positive = _swap_permutation(positive, rng)
    elif kind is MoveKind.SWAP_NEGATIVE:
        negative = _swap_permutation(negative, rng)
    elif kind is MoveKind.SWAP_BOTH:
        first, second = rng.sample(range(size), 2)
        first_strip = positive[first]
        second_strip = positive[second]
        positive = _swap_positions(positive, first, second)
        negative = _swap_positions(
            negative,
            negative.index(first_strip),
            negative.index(second_strip),
        )
    elif kind is MoveKind.INSERT_POSITIVE:
        positive = _insert_permutation(positive, rng)
    elif kind is MoveKind.INSERT_NEGATIVE:
        negative = _insert_permutation(negative, rng)
    elif kind is MoveKind.CHANGE_VARIANT:
        if problem is None or not problem.variant_tables:
            return state
        problem.selected_sizes(state.variant_indices)
        mutable = tuple(
            strip for strip, variants in enumerate(problem.variant_tables) if len(variants) > 1
        )
        if not mutable:
            return state
        strip = rng.choice(mutable)
        current = state.variant_indices[strip]
        variant = rng.randrange(len(problem.variant_tables[strip]) - 1)
        if variant >= current:
            variant += 1
        return apply_variant_move(problem, state, strip=strip, variant=variant)
    else:
        gaps = _step_gap(gaps, rng)

    return AnnealState(
        pair=SequencePair(positive, negative),
        gaps=gaps,
        base_seed=state.base_seed,
        stage_index=state.stage_index,
        variant_indices=state.variant_indices,
    )


def score_candidate(
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    context: PlacementCostContext,
) -> EnergyBreakdown:
    """Compute one candidate's complete geometry and routing-proxy observation."""
    if len(decoded.x) != problem.size:
        raise ValueError("decoded placement size must match the placement problem")
    if context.net_pairs != problem.nets:
        raise ValueError("placement cost context must match the problem net identities")
    if context.history_outline[1] != problem.outline_height:
        raise ValueError("placement cost context must match the problem outline height")
    sizes = problem.selected_sizes(decoded.variant_indices)
    for target in context.direct_targets:
        _validate_direct_target(problem, target, sizes)

    weighted_hpwl = sum(
        context.net_weights[index]
        * (
            abs(decoded.x[source] - decoded.x[destination])
            + abs(decoded.y[source] - decoded.y[destination])
        )
        for index, (source, destination) in enumerate(context.net_pairs)
    )
    return EnergyBreakdown(
        width=decoded.width,
        used_height=decoded.used_height,
        box_area=sum(width * height for width, height in sizes),
        gap_area=decoded.gap_area,
        weighted_hpwl=weighted_hpwl,
        history_cost=_candidate_history_cost(decoded, context, sizes),
        missed_direct_inserts=sum(
            not _target_is_direct(decoded, target) for target in context.direct_targets
        ),
        hard_outline_overflow=max(0, decoded.used_height - problem.outline_height),
        outline_height=problem.outline_height,
        area_lower_bound=problem.area_lower_bound,
        net_count=len(context.net_pairs),
    )


def cheap_energy(
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    context: PlacementCostContext,
) -> SearchEnergy:
    """Return the blended objective derived from the complete candidate score."""
    return score_candidate(problem, decoded, context).energy


def _candidate_history_cost(
    decoded: DecodedPlacement,
    context: PlacementCostContext,
    sizes: tuple[tuple[int, int], ...],
) -> float:
    width, height = context.history_outline
    stride = width + 1
    table = context.history_summed_area
    total = 0.0
    for source, destination in context.net_pairs:
        source_width, source_height = sizes[source]
        destination_width, destination_height = sizes[destination]
        x0 = min(width, max(0, min(decoded.x[source], decoded.x[destination])))
        y0 = min(height, max(0, min(decoded.y[source], decoded.y[destination])))
        x1 = min(
            width,
            max(
                decoded.x[source] + source_width,
                decoded.x[destination] + destination_width,
            ),
        )
        y1 = min(
            height,
            max(
                decoded.y[source] + source_height,
                decoded.y[destination] + destination_height,
            ),
        )
        total += (
            table[y1 * stride + x1]
            - table[y0 * stride + x1]
            - table[y1 * stride + x0]
            + table[y0 * stride + x0]
        )
    return total


def anneal_stage(
    problem: PlacementProblem,
    state: AnnealState,
    config: AnnealConfig,
    context: PlacementCostContext | None = None,
    *,
    direct_targets_for_state: Callable[
        [PlacementProblem, AnnealState], tuple[DirectInsertTarget, ...]
    ]
    | None = None,
) -> AnnealStageResult:
    """Run exactly one reproducible linearly cooled block of cheap SA moves."""
    state.pair.validate(problem.size)
    if len(state.gaps.east) != problem.size:
        raise ValueError("annealing state size must match the placement problem")
    problem.selected_sizes(state.variant_indices)
    if context is None:
        context = PlacementCostContext(
            net_weights=(1.0,) * len(problem.nets),
            net_pairs=problem.nets,
            history_outline=(0, problem.outline_height),
            history_summed_area=(0.0,) * (problem.outline_height + 1),
        )

    rng = random.Random(derive_stage_seed(state.base_seed, state.stage_index))
    current = _score_state(problem, state, context, direct_targets_for_state)
    archive = build_elite_archive((current,), config.elite_count)
    accepted_moves = 0
    move_kinds = tuple(MoveKind)

    for move_index in range(config.moves_per_stage):
        candidate_state = apply_move(
            state=current.state,
            kind=rng.choice(move_kinds),
            rng=rng,
            problem=problem,
        )
        candidate = _score_state(
            problem,
            candidate_state,
            context,
            direct_targets_for_state,
        )
        archive = build_elite_archive(
            (*(entry.incumbent for entry in archive), candidate),
            config.elite_count,
        )
        temperature = _linear_temperature(config, move_index)
        if _accept_move(current.energy, candidate.energy, temperature, rng):
            current = candidate
            accepted_moves += 1

    final_state = AnnealState(
        pair=current.state.pair,
        gaps=current.state.gaps,
        base_seed=state.base_seed,
        stage_index=state.stage_index + 1,
        variant_indices=current.state.variant_indices,
    )
    return AnnealStageResult(
        final_state=final_state,
        incumbent=archive[0].incumbent,
        accepted_moves=accepted_moves,
        archive=archive,
    )


def repair_neighbourhood(
    pair: SequencePair,
    gaps: GapProfile,
    neighbourhood: frozenset[int],
    *,
    seed: int,
    strip_weights: Mapping[int, float] | None = None,
    variant_indices: tuple[int, ...] = (),
) -> AnnealState:
    """Deterministically destroy and repair only selected sequence-pair strips."""
    size = len(pair.positive)
    if len(gaps.east) != size:
        raise ValueError("LNS pair and gap profile sizes must match")
    if not isinstance(neighbourhood, frozenset) or any(
        type(strip) is not int or not 0 <= strip < size for strip in neighbourhood
    ):
        raise ValueError("LNS neighbourhood must be a frozen set of valid strip IDs")
    if type(seed) is not int:
        raise ValueError("LNS seed must be an integer")
    weights = dict(strip_weights or {})
    if any(
        type(strip) is not int
        or not 0 <= strip < size
        or not math.isfinite(weight)
        or weight <= 0.0
        for strip, weight in weights.items()
    ):
        raise ValueError("LNS strip weights must be finite positive values")

    rng = random.Random(derive_stage_seed(seed, 0))
    order = tuple(
        sorted(
            sorted(neighbourhood),
            key=lambda strip: (
                -math.log(max(rng.random(), float.fromhex("0x1p-1074"))) / weights.get(strip, 1.0),
                strip,
            ),
        )
    )
    positive = _repair_permutation(pair.positive, neighbourhood, order, rng)
    negative = _repair_permutation(pair.negative, neighbourhood, order, rng)
    east = list(gaps.east)
    north = list(gaps.north)
    for strip in order:
        values = east if rng.randrange(2) == 0 else north
        values[strip] = min(_MAX_GAP, max(0, values[strip] + rng.choice((-1, 1))))
    return AnnealState(
        pair=SequencePair(positive, negative),
        gaps=GapProfile(tuple(east), tuple(north)),
        base_seed=seed,
        variant_indices=variant_indices,
    )


def split_stage_boundary(
    problem: PlacementProblem,
    state: AnnealState,
    family: StripFamily,
    strip: int,
    *,
    right_variant_offset: int = 0,
) -> StageBoundaryUpdate:
    """Replace one instance with exact child ranges between annealing stages."""
    from flab2bp.layout.strip_variants import (
        StripInstance,
        split_strip_instance,
    )

    problem._validate_variant_indices(state.variant_indices)
    if not problem.variant_tables:
        raise ValueError("stage-boundary split requires a variant-aware problem")
    if type(strip) is not int or not 0 <= strip < problem.size:
        raise ValueError("split target must identify a placement strip")
    if type(right_variant_offset) is not int or right_variant_offset < 0:
        raise ValueError("right child variant offset must be non-negative")
    instance_id = problem.instance_ids[strip]
    if instance_id.family_id != family.family_id:
        raise ValueError("split target belongs to another logical family")
    selected = problem.variant(strip, state.variant_indices[strip])
    parent = StripInstance(
        instance_id=instance_id,
        machine_start=instance_id.machine_start,
        machine_count=instance_id.machine_count,
        variant=selected,
    )
    family_templates = {
        variant.template_key: index for index, variant in enumerate(family.variants)
    }
    try:
        selected_family_index = family_templates[selected.template_key]
    except KeyError:
        raise ValueError("selected split variant is outside its logical family") from None
    right_family_index = (selected_family_index + right_variant_offset) % len(family.variants)
    left, right = split_strip_instance(
        family,
        parent,
        child_variant_indices=(selected_family_index, right_family_index),
    )

    parent_table = problem.variant_tables[strip]
    child_tables = tuple(
        _realized_table_in_parent_order(family, parent_table, child.machine_count)
        for child in (left, right)
    )
    selected_keys = (left.variant.template_key, right.variant.template_key)
    child_indices = tuple(
        next(index for index, variant in enumerate(table) if variant.template_key == selected_key)
        for table, selected_key in zip(child_tables, selected_keys, strict=True)
    )
    width_padding = problem.sizes[strip][0] - parent_table[0].box_width
    height_padding = problem.sizes[strip][1] - parent_table[0].box_height
    child_sizes = tuple(
        (table[0].box_width + width_padding, table[0].box_height + height_padding)
        for table in child_tables
    )

    def expanded(index: int) -> tuple[int, ...]:
        if index < strip:
            return (index,)
        if index == strip:
            return (strip, strip + 1)
        return (index + 1,)

    pair = SequencePair(
        tuple(child for index in state.pair.positive for child in expanded(index)),
        tuple(child for index in state.pair.negative for child in expanded(index)),
    )
    gaps = GapProfile(
        state.gaps.east[:strip] + (state.gaps.east[strip], 0) + state.gaps.east[strip + 1 :],
        state.gaps.north[:strip] + (state.gaps.north[strip], 0) + state.gaps.north[strip + 1 :],
    )
    variant_indices = (
        state.variant_indices[:strip] + child_indices + state.variant_indices[strip + 1 :]
    )
    nets, logical_net_ids = _remap_nets(
        problem.nets,
        problem.logical_net_ids,
        expanded,
    )
    rebuilt_ids = (
        problem.instance_ids[:strip]
        + (left.instance_id, right.instance_id)
        + problem.instance_ids[strip + 1 :]
    )
    rebuilt = PlacementProblem(
        sizes=problem.sizes[:strip] + child_sizes + problem.sizes[strip + 1 :],
        nets=nets,
        outline_height=problem.outline_height,
        area_lower_bound=problem.area_lower_bound,
        instance_ids=rebuilt_ids,
        variant_tables=problem.variant_tables[:strip]
        + child_tables
        + problem.variant_tables[strip + 1 :],
        logical_net_ids=logical_net_ids,
    )
    return StageBoundaryUpdate(
        problem=rebuilt,
        state=AnnealState(
            pair=pair,
            gaps=gaps,
            base_seed=state.base_seed,
            stage_index=state.stage_index,
            variant_indices=variant_indices,
        ),
    )


def merge_stage_boundary(
    problem: PlacementProblem,
    state: AnnealState,
    family: StripFamily,
    left_strip: int,
    right_strip: int,
) -> StageBoundaryUpdate | None:
    """Collapse compatible adjacent children between stages."""
    from flab2bp.layout.strip_variants import (
        StripInstance,
        merge_strip_instances,
    )

    problem._validate_variant_indices(state.variant_indices)
    if (
        not problem.variant_tables
        or type(left_strip) is not int
        or type(right_strip) is not int
        or right_strip != left_strip + 1
        or not 0 <= left_strip < right_strip < problem.size
    ):
        return None
    left_id, right_id = problem.instance_ids[left_strip : right_strip + 1]
    left_variant = problem.variant(left_strip, state.variant_indices[left_strip])
    right_variant = problem.variant(right_strip, state.variant_indices[right_strip])
    left = StripInstance(
        left_id,
        left_id.machine_start,
        left_id.machine_count,
        left_variant,
    )
    right = StripInstance(
        right_id,
        right_id.machine_start,
        right_id.machine_count,
        right_variant,
    )
    merged = merge_strip_instances(family, left, right)
    if merged is None:
        return None
    for permutation in (state.pair.positive, state.pair.negative):
        position = permutation.index(left_strip)
        if position + 1 >= len(permutation) or permutation[position + 1] != right_strip:
            return None
    if state.gaps.east[right_strip] or state.gaps.north[right_strip]:
        return None

    merged_table = _realized_table_in_parent_order(
        family,
        problem.variant_tables[left_strip],
        merged.machine_count,
    )
    selected_index = next(
        index
        for index, variant in enumerate(merged_table)
        if variant.template_key == merged.variant.template_key
    )
    width_padding = problem.sizes[left_strip][0] - problem.variant_tables[left_strip][0].box_width
    height_padding = problem.sizes[left_strip][1] - problem.variant_tables[left_strip][0].box_height

    def collapsed(index: int) -> tuple[int, ...]:
        if index == right_strip:
            return ()
        if index < right_strip:
            return (index,)
        return (index - 1,)

    pair = SequencePair(
        tuple(child for index in state.pair.positive for child in collapsed(index)),
        tuple(child for index in state.pair.negative for child in collapsed(index)),
    )
    nets, logical_net_ids = _remap_nets(
        problem.nets,
        problem.logical_net_ids,
        collapsed,
    )
    rebuilt_ids = (
        problem.instance_ids[:left_strip]
        + (merged.instance_id,)
        + problem.instance_ids[right_strip + 1 :]
    )
    rebuilt = PlacementProblem(
        sizes=problem.sizes[:left_strip]
        + (
            (
                merged_table[0].box_width + width_padding,
                merged_table[0].box_height + height_padding,
            ),
        )
        + problem.sizes[right_strip + 1 :],
        nets=nets,
        outline_height=problem.outline_height,
        area_lower_bound=problem.area_lower_bound,
        instance_ids=rebuilt_ids,
        variant_tables=problem.variant_tables[:left_strip]
        + (merged_table,)
        + problem.variant_tables[right_strip + 1 :],
        logical_net_ids=logical_net_ids,
    )
    return StageBoundaryUpdate(
        problem=rebuilt,
        state=AnnealState(
            pair=pair,
            gaps=GapProfile(
                state.gaps.east[:left_strip]
                + (state.gaps.east[left_strip],)
                + state.gaps.east[right_strip + 1 :],
                state.gaps.north[:left_strip]
                + (state.gaps.north[left_strip],)
                + state.gaps.north[right_strip + 1 :],
            ),
            base_seed=state.base_seed,
            stage_index=state.stage_index,
            variant_indices=state.variant_indices[:left_strip]
            + (selected_index,)
            + state.variant_indices[right_strip + 1 :],
        ),
    )


def _realized_table_in_parent_order(
    family: StripFamily,
    parent_table: tuple[StripVariant, ...],
    machine_count: int,
) -> tuple[StripVariant, ...]:
    from flab2bp.layout.strip_variants import variants_for_count

    realized = {
        variant.template_key: variant for variant in variants_for_count(family, machine_count)
    }
    try:
        return tuple(realized[variant.template_key] for variant in parent_table)
    except KeyError:
        raise ValueError("variant table contains a pose outside its logical family") from None


def _remap_nets(
    nets: tuple[tuple[int, int], ...],
    logical_net_ids: tuple[LogicalNetId, ...],
    remap: Callable[[int], tuple[int, ...]],
) -> tuple[tuple[tuple[int, int], ...], tuple[LogicalNetId, ...]]:
    rebuilt: list[tuple[int, int]] = []
    rebuilt_logical: list[LogicalNetId] = []
    seen: set[tuple[tuple[int, int], LogicalNetId | None]] = set()
    logical_keys: tuple[LogicalNetId | None, ...] = logical_net_ids or (None,) * len(nets)
    for (source, destination), logical in zip(nets, logical_keys, strict=True):
        for new_source in remap(source):
            for new_destination in remap(destination):
                net = (new_source, new_destination)
                key = (net, logical)
                if key in seen:
                    continue
                seen.add(key)
                rebuilt.append(net)
                if logical is not None:
                    rebuilt_logical.append(logical)
    return tuple(rebuilt), tuple(rebuilt_logical)


def _repair_permutation(
    permutation: tuple[int, ...],
    neighbourhood: frozenset[int],
    order: tuple[int, ...],
    rng: random.Random,
) -> tuple[int, ...]:
    repaired = [strip for strip in permutation if strip not in neighbourhood]
    for strip in order:
        repaired.insert(rng.randrange(len(repaired) + 1), strip)
    return tuple(repaired)


def _score_state(
    problem: PlacementProblem,
    state: AnnealState,
    context: PlacementCostContext,
    direct_targets_for_state: Callable[
        [PlacementProblem, AnnealState], tuple[DirectInsertTarget, ...]
    ]
    | None = None,
) -> AnnealIncumbent:
    decoded = decode_state(problem, state)
    dimensions = problem.selected_sizes(state.variant_indices)
    candidate_context = (
        replace(
            context,
            direct_targets=direct_targets_for_state(problem, state),
        )
        if direct_targets_for_state is not None
        else context
    )
    breakdown = score_candidate(problem, decoded, candidate_context)
    return AnnealIncumbent(
        state=state,
        decoded=decoded,
        breakdown=breakdown,
        key=PlacementKey(
            x=decoded.x,
            y=decoded.y,
            dimensions=dimensions,
            east_gaps=state.gaps.east,
            north_gaps=state.gaps.north,
            instance_ids=problem.instance_ids,
            variant_ids=problem.selected_variant_ids(state.variant_indices),
        ),
    )


def build_elite_archive(
    candidates: Iterable[AnnealIncumbent],
    elite_count: int,
) -> tuple[TaggedAnnealIncumbent, ...]:
    """Return a capped deterministic union of mandatory category winners."""
    if type(elite_count) is not int or elite_count <= 0:
        raise ValueError("elite count must be a positive integer")

    distinct: dict[PlacementKey, AnnealIncumbent] = {}
    for candidate in candidates:
        previous = distinct.get(candidate.key)
        if previous is None or _archive_dedupe_key(candidate) < _archive_dedupe_key(previous):
            distinct[candidate.key] = candidate
    if not distinct:
        return ()

    values = tuple(distinct.values())
    mandatory = (
        (EliteCategory.BLENDED, min(values, key=_blended_archive_key)),
        (EliteCategory.NARROWEST, min(values, key=_narrowest_archive_key)),
        (EliteCategory.LOWEST_HPWL, min(values, key=_lowest_hpwl_archive_key)),
        (EliteCategory.LOWEST_HISTORY, min(values, key=_lowest_history_archive_key)),
    )
    order: list[PlacementKey] = []
    categories_by_key: dict[PlacementKey, list[EliteCategory]] = {}
    for category, winner in mandatory:
        categories = categories_by_key.get(winner.key)
        if categories is None:
            order.append(winner.key)
            categories_by_key[winner.key] = [category]
        else:
            categories.append(category)

    effective_cap = max(elite_count, len(order))
    for candidate in sorted(values, key=_blended_archive_key):
        if len(order) >= effective_cap:
            break
        if candidate.key in categories_by_key:
            continue
        order.append(candidate.key)
        categories_by_key[candidate.key] = [EliteCategory.BLENDED]

    return tuple(
        TaggedAnnealIncumbent(
            incumbent=distinct[key],
            categories=tuple(categories_by_key[key]),
        )
        for key in order
    )


def _blended_archive_key(candidate: AnnealIncumbent) -> tuple[SearchEnergy, PlacementKey]:
    return candidate.energy, candidate.key


def _narrowest_archive_key(
    candidate: AnnealIncumbent,
) -> tuple[int, int, int, int, float, PlacementKey]:
    breakdown = candidate.breakdown
    return (
        breakdown.hard_outline_overflow,
        breakdown.width,
        breakdown.used_height,
        breakdown.gap_area,
        breakdown.weighted_hpwl,
        candidate.key,
    )


def _lowest_hpwl_archive_key(
    candidate: AnnealIncumbent,
) -> tuple[int, float, int, int, PlacementKey]:
    breakdown = candidate.breakdown
    return (
        breakdown.hard_outline_overflow,
        breakdown.weighted_hpwl,
        breakdown.width,
        breakdown.gap_area,
        candidate.key,
    )


def _lowest_history_archive_key(
    candidate: AnnealIncumbent,
) -> tuple[int, float, int, float, PlacementKey]:
    breakdown = candidate.breakdown
    return (
        breakdown.hard_outline_overflow,
        breakdown.history_cost,
        breakdown.width,
        breakdown.weighted_hpwl,
        candidate.key,
    )


def _archive_dedupe_key(
    candidate: AnnealIncumbent,
) -> tuple[
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
    tuple[int, ...],
    int,
    int,
    int,
    int,
    int,
    int,
    float,
    float,
    int,
    int,
    int,
    int,
    int,
    tuple[tuple[int, int], ...],
    tuple[tuple[int, int], ...],
    tuple[tuple[int, int], ...],
]:
    state = candidate.state
    breakdown = candidate.breakdown
    return (
        state.pair.positive,
        state.pair.negative,
        state.gaps.east,
        state.gaps.north,
        state.variant_indices,
        state.base_seed,
        state.stage_index,
        breakdown.width,
        breakdown.used_height,
        breakdown.box_area,
        breakdown.gap_area,
        breakdown.weighted_hpwl,
        breakdown.history_cost,
        breakdown.missed_direct_inserts,
        breakdown.hard_outline_overflow,
        breakdown.outline_height,
        breakdown.area_lower_bound,
        breakdown.net_count,
        candidate.decoded.x_windows,
        candidate.decoded.y_windows,
        tuple(sorted(candidate.decoded.direct)),
    )


def _linear_temperature(config: AnnealConfig, move_index: int) -> float:
    if config.moves_per_stage == 1:
        return config.initial_temperature
    progress = move_index / (config.moves_per_stage - 1)
    return config.initial_temperature + progress * (
        config.final_temperature - config.initial_temperature
    )


def _accept_move(
    current: SearchEnergy,
    candidate: SearchEnergy,
    temperature: float,
    rng: random.Random,
) -> bool:
    if candidate.hard_outline_overflow != current.hard_outline_overflow:
        return candidate.hard_outline_overflow < current.hard_outline_overflow
    delta = candidate.scalar - current.scalar
    return delta <= 0.0 or rng.random() < math.exp(-delta / temperature)


def _swap_permutation(permutation: tuple[int, ...], rng: random.Random) -> tuple[int, ...]:
    first, second = rng.sample(range(len(permutation)), 2)
    return _swap_positions(permutation, first, second)


def _swap_positions(permutation: tuple[int, ...], first: int, second: int) -> tuple[int, ...]:
    values = list(permutation)
    values[first], values[second] = values[second], values[first]
    return tuple(values)


def _insert_permutation(permutation: tuple[int, ...], rng: random.Random) -> tuple[int, ...]:
    source, destination = rng.sample(range(len(permutation)), 2)
    values = list(permutation)
    strip = values.pop(source)
    values.insert(destination, strip)
    return tuple(values)


def _step_gap(gaps: GapProfile, rng: random.Random) -> GapProfile:
    size = len(gaps.east)
    if size == 0:
        return gaps
    mutate_east = rng.randrange(2) == 0
    values = list(gaps.east if mutate_east else gaps.north)
    index = rng.randrange(size)
    if values[index] == 0:
        step = 1
    elif values[index] == _MAX_GAP:
        step = -1
    else:
        step = 1 if rng.randrange(2) == 0 else -1
    values[index] += step
    if mutate_east:
        return GapProfile(tuple(values), gaps.north)
    return GapProfile(gaps.east, tuple(values))


def _validate_sizes(sizes: tuple[tuple[int, int], ...]) -> None:
    if not isinstance(sizes, tuple):
        raise ValueError("rectangle sizes must be an immutable tuple")
    if any(
        not isinstance(rectangle, tuple)
        or len(rectangle) != 2
        or any(type(dimension) is not int or dimension <= 0 for dimension in rectangle)
        for rectangle in sizes
    ):
        raise ValueError("rectangle sizes must contain positive integer width-height pairs")


def _validate_positive_integer(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _earliest_coordinates(
    successors: list[list[int]],
    topological_order: tuple[int, ...],
    dimensions: tuple[int, ...],
    slack: tuple[int, ...],
) -> tuple[int, ...]:
    coordinates = [0] * len(dimensions)
    for source in topological_order:
        after_source = coordinates[source] + dimensions[source] + slack[source]
        for destination in successors[source]:
            coordinates[destination] = max(coordinates[destination], after_source)
    return tuple(coordinates)


def _latest_coordinates(
    successors: list[list[int]],
    topological_order: tuple[int, ...],
    dimensions: tuple[int, ...],
    slack: tuple[int, ...],
    outline: int,
) -> tuple[int, ...]:
    coordinates = [outline - dimension for dimension in dimensions]
    for source in reversed(topological_order):
        source_span = dimensions[source] + slack[source]
        for destination in successors[source]:
            coordinates[source] = min(coordinates[source], coordinates[destination] - source_span)
    return tuple(coordinates)
