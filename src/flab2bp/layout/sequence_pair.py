"""Deterministic fixed-orientation sequence-pair placement."""

from __future__ import annotations

from dataclasses import dataclass

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
