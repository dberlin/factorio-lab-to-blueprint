"""Deterministic fixed-orientation sequence-pair placement."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum

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
class DecodedPlacement:
    """Earliest coordinates and legal coordinate windows for one sequence pair."""

    x: tuple[int, ...]
    y: tuple[int, ...]
    width: int
    used_height: int
    x_windows: tuple[tuple[int, int], ...]
    y_windows: tuple[tuple[int, int], ...]
    gap_area: int

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
        if any(
            window[0] != coordinate
            for coordinate, window in zip(self.x, self.x_windows, strict=True)
        ):
            raise ValueError("x window earliest coordinates must match decoded x coordinates")
        if any(
            window[0] != coordinate
            for coordinate, window in zip(self.y, self.y_windows, strict=True)
        ):
            raise ValueError("y window earliest coordinates must match decoded y coordinates")
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
    """Per-net feedback inputs used by cheap placement scoring."""

    net_weights: tuple[float, ...]
    history_cost_by_net: tuple[float, ...]
    missed_direct_inserts: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.net_weights, tuple) or not isinstance(
            self.history_cost_by_net, tuple
        ):
            raise ValueError("placement cost context values must be immutable tuples")
        if any(
            not math.isfinite(value) or value < 0.0
            for value in self.net_weights + self.history_cost_by_net
        ):
            raise ValueError("placement cost context values must be finite and non-negative")
        if type(self.missed_direct_inserts) is not int or self.missed_direct_inserts < 0:
            raise ValueError("missed direct inserts must be a non-negative integer")


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
    if (
        len(context.net_weights) != len(problem.nets)
        or len(context.history_cost_by_net) != len(problem.nets)
    ):
        raise ValueError("placement cost context must match the problem net count")
    overflow = max(0, decoded.used_height - problem.outline_height)
    area_ratio = decoded.width * problem.outline_height / max(problem.area_lower_bound, 1)
    weighted_hpwl = sum(
        context.net_weights[index]
        * (
            abs(decoded.x[source] - decoded.x[destination])
            + abs(decoded.y[source] - decoded.y[destination])
        )
        for index, (source, destination) in enumerate(problem.nets)
    )
    hpwl_ratio = weighted_hpwl / max(problem.area_lower_bound, 1)
    history_ratio = sum(context.history_cost_by_net) / max(len(problem.nets), 1)
    direct_ratio = context.missed_direct_inserts / max(len(problem.nets), 1)
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
            history_cost_by_net=(0.0,) * len(problem.nets),
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

    ordered_elites = tuple(
        sorted(elites.values(), key=lambda elite: (elite.energy, elite.key))
    )
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


def _swap_permutation(
    permutation: tuple[int, ...], rng: random.Random
) -> tuple[int, ...]:
    first, second = rng.sample(range(len(permutation)), 2)
    return _swap_positions(permutation, first, second)


def _swap_positions(
    permutation: tuple[int, ...], first: int, second: int
) -> tuple[int, ...]:
    values = list(permutation)
    values[first], values[second] = values[second], values[first]
    return tuple(values)


def _insert_permutation(
    permutation: tuple[int, ...], rng: random.Random
) -> tuple[int, ...]:
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
