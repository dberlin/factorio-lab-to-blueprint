"""Deterministic fixed-orientation sequence-pair placement."""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from flab2bp.dsp import catalog

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
    """Fixed rectangle geometry and net endpoints for placement search."""

    sizes: tuple[tuple[int, int], ...]
    nets: tuple[tuple[int, int], ...]
    outline_height: int
    area_lower_bound: int

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

    @property
    def size(self) -> int:
        return len(self.sizes)


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


@dataclass(frozen=True, slots=True)
class AnnealState:
    """Immutable sequence-pair state and deterministic multi-stage seed ownership."""

    pair: SequencePair
    gaps: GapProfile
    base_seed: int
    stage_index: int = 0

    def __post_init__(self) -> None:
        if len(self.gaps.east) != len(self.pair.positive):
            raise ValueError("annealing pair and gap profile sizes must match")
        if type(self.base_seed) is not int:
            raise ValueError("annealing base seed must be an integer")
        if type(self.stage_index) is not int or self.stage_index < 0:
            raise ValueError("annealing stage index must be a non-negative integer")

    @classmethod
    def initial(cls, size: int, seed: int) -> AnnealState:
        """Create a reproducible independently shuffled sequence-pair start."""
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
        )


@dataclass(frozen=True, order=True, slots=True)
class PlacementKey:
    """Exact immutable identity for retaining distinct decoded placements."""

    x: tuple[int, ...]
    y: tuple[int, ...]
    dimensions: tuple[tuple[int, int], ...]
    east_gaps: tuple[int, ...]
    north_gaps: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AnnealIncumbent:
    """Scored annealing state retained at a stage boundary."""

    state: AnnealState
    decoded: DecodedPlacement
    energy: SearchEnergy
    key: PlacementKey


@dataclass(frozen=True, slots=True)
class AnnealStageResult:
    """Result of exactly one deterministic temperature stage."""

    final_state: AnnealState
    incumbent: AnnealIncumbent
    accepted_moves: int
    elites: tuple[AnnealIncumbent, ...]


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
        _validate_direct_target(problem, carried)
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
        _validate_direct_target(problem, target)
        if target.key in current.direct:
            continue
        candidate = _align_direct_target(
            problem,
            current,
            target,
            outline=(decoded.width, decoded.used_height),
        )
        if candidate is None:
            continue
        if not _preserves_separations(decoded, candidate, problem.sizes):
            continue
        if not all(
            _target_is_direct(candidate, accepted)
            for accepted in (*realized_targets.values(), target)
        ):
            continue
        current = candidate
        realized_targets[target.key] = target
    return current


def _validate_direct_target(problem: PlacementProblem, target: DirectInsertTarget) -> None:
    if not 0 <= target.producer < problem.size or not 0 <= target.consumer < problem.size:
        raise ValueError("direct-insert target endpoints must identify placement strips")
    producer_size = problem.sizes[target.producer]
    consumer_size = problem.sizes[target.consumer]
    if (
        target.producer_row >= producer_size[1]
        or target.consumer_row >= consumer_size[1]
        or target.producer_span > producer_size[0]
        or target.consumer_span > consumer_size[0]
    ):
        raise ValueError("direct-insert target geometry must lie inside its endpoint strips")


def _align_direct_target(
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    target: DirectInsertTarget,
    *,
    outline: tuple[int, int],
) -> DecodedPlacement | None:
    producer = target.producer
    consumer = target.consumer
    producer_width, producer_height = problem.sizes[producer]
    consumer_width, consumer_height = problem.sizes[consumer]

    producer_x_bounds = _relation_bounds(decoded, problem.sizes, producer, consumer, axis=0)
    consumer_x_bounds = _relation_bounds(decoded, problem.sizes, consumer, producer, axis=0)
    producer_y_bounds = _relation_bounds(decoded, problem.sizes, producer, consumer, axis=1)
    consumer_y_bounds = _relation_bounds(decoded, problem.sizes, consumer, producer, axis=1)

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
    width = max(coordinate + size[0] for coordinate, size in zip(x, problem.sizes, strict=True))
    used_height = max(
        coordinate + size[1] for coordinate, size in zip(y, problem.sizes, strict=True)
    )
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
    )
    if not _no_overlaps(candidate, problem.sizes):
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


def apply_move(state: AnnealState, kind: MoveKind, rng: random.Random) -> AnnealState:
    """Apply one legal local move while preserving immutable state ownership."""
    if not isinstance(kind, MoveKind):
        raise ValueError("unknown annealing move kind")
    size = len(state.pair.positive)
    if size == 0 or (size == 1 and kind is not MoveKind.GAP_STEP):
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
    else:
        gaps = _step_gap(gaps, rng)

    return AnnealState(
        pair=SequencePair(positive, negative),
        gaps=gaps,
        base_seed=state.base_seed,
        stage_index=state.stage_index,
    )


def cheap_energy(
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    context: PlacementCostContext,
) -> SearchEnergy:
    """Compute the normalized routing-aware proxy objective."""
    if len(decoded.x) != problem.size:
        raise ValueError("decoded placement size must match the placement problem")
    if context.net_pairs != problem.nets:
        raise ValueError("placement cost context must match the problem net identities")
    if context.history_outline[1] != problem.outline_height:
        raise ValueError("placement cost context must match the problem outline height")
    for target in context.direct_targets:
        _validate_direct_target(problem, target)

    overflow = max(0, decoded.used_height - problem.outline_height)
    area_ratio = decoded.width * problem.outline_height / max(problem.area_lower_bound, 1)
    weighted_hpwl = sum(
        context.net_weights[index]
        * (
            abs(decoded.x[source] - decoded.x[destination])
            + abs(decoded.y[source] - decoded.y[destination])
        )
        for index, (source, destination) in enumerate(context.net_pairs)
    )
    hpwl_ratio = weighted_hpwl / max(problem.area_lower_bound, 1)
    history_ratio = _candidate_history_cost(problem, decoded, context) / max(
        len(context.net_pairs), 1
    )
    direct_ratio = sum(
        not _target_is_direct(decoded, target) for target in context.direct_targets
    ) / max(len(context.net_pairs), 1)
    gap_ratio = decoded.gap_area / max(problem.area_lower_bound, 1)
    return SearchEnergy(
        hard_outline_overflow=overflow,
        scalar=(
            area_ratio
            + 0.35 * hpwl_ratio
            + 0.2 * history_ratio
            + 0.1 * direct_ratio
            + 0.05 * gap_ratio
        ),
    )


def _candidate_history_cost(
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    context: PlacementCostContext,
) -> float:
    width, height = context.history_outline
    stride = width + 1
    table = context.history_summed_area
    total = 0.0
    for source, destination in context.net_pairs:
        source_width, source_height = problem.sizes[source]
        destination_width, destination_height = problem.sizes[destination]
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
) -> AnnealStageResult:
    """Run exactly one reproducible linearly cooled block of cheap SA moves."""
    state.pair.validate(problem.size)
    if len(state.gaps.east) != problem.size:
        raise ValueError("annealing state size must match the placement problem")
    if context is None:
        context = PlacementCostContext(
            net_weights=(1.0,) * len(problem.nets),
            net_pairs=problem.nets,
            history_outline=(0, problem.outline_height),
            history_summed_area=(0.0,) * (problem.outline_height + 1),
        )

    rng = random.Random(derive_stage_seed(state.base_seed, state.stage_index))
    current = _score_state(problem, state, context)
    elites: dict[PlacementKey, AnnealIncumbent] = {current.key: current}
    accepted_moves = 0
    move_kinds = tuple(MoveKind)

    for move_index in range(config.moves_per_stage):
        candidate_state = apply_move(state=current.state, kind=rng.choice(move_kinds), rng=rng)
        candidate = _score_state(problem, candidate_state, context)
        _retain_elite(elites, candidate, config.elite_count)
        temperature = _linear_temperature(config, move_index)
        if _accept_move(current.energy, candidate.energy, temperature, rng):
            current = candidate
            accepted_moves += 1

    ordered_elites = tuple(sorted(elites.values(), key=lambda elite: (elite.energy, elite.key)))
    final_state = AnnealState(
        pair=current.state.pair,
        gaps=current.state.gaps,
        base_seed=state.base_seed,
        stage_index=state.stage_index + 1,
    )
    return AnnealStageResult(
        final_state=final_state,
        incumbent=ordered_elites[0],
        accepted_moves=accepted_moves,
        elites=ordered_elites,
    )


def repair_neighbourhood(
    pair: SequencePair,
    gaps: GapProfile,
    neighbourhood: frozenset[int],
    *,
    seed: int,
    strip_weights: Mapping[int, float] | None = None,
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
    )


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
) -> AnnealIncumbent:
    decoded = decode_sequence_pair(
        state.pair,
        state.gaps,
        problem.sizes,
        outline_height=problem.outline_height,
    )
    return AnnealIncumbent(
        state=state,
        decoded=decoded,
        energy=cheap_energy(problem, decoded, context),
        key=PlacementKey(
            x=decoded.x,
            y=decoded.y,
            dimensions=problem.sizes,
            east_gaps=state.gaps.east,
            north_gaps=state.gaps.north,
        ),
    )


def _retain_elite(
    elites: dict[PlacementKey, AnnealIncumbent],
    candidate: AnnealIncumbent,
    elite_count: int,
) -> None:
    previous = elites.get(candidate.key)
    if previous is not None and previous.energy <= candidate.energy:
        return
    elites[candidate.key] = candidate
    if len(elites) > elite_count:
        worst = max(elites.values(), key=lambda elite: (elite.energy, elite.key))
        del elites[worst.key]


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
