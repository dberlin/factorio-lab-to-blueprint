"""Typed latitude-band selection shared by layout entry points."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import cast

type BandSelection = str
type BandDimension = tuple[int, int]


def _load_band_dimensions() -> tuple[BandDimension, ...]:
    source = files("flab2bp.dsp").joinpath("data/latitude_bands.json")
    raw = cast(object, json.loads(source.read_text(encoding="utf-8")))
    if not isinstance(raw, list):
        raise RuntimeError(f"{source} must contain a JSON array")

    dimensions: list[BandDimension] = []
    segments: set[int] = set()
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            raise RuntimeError(f"{source} contains a malformed latitude band")
        record = cast(dict[object, object], item)
        if set(record) != {"height", "width"}:
            raise RuntimeError(f"{source} contains a malformed latitude band")
        height = record["height"]
        width = record["width"]
        if (
            not isinstance(height, int)
            or isinstance(height, bool)
            or not isinstance(width, int)
            or isinstance(width, bool)
            or height <= 0
            or width <= 0
            or width % 5
        ):
            raise RuntimeError(f"{source} contains an invalid latitude-band dimension")
        dimension = (height, width)
        area_segments = width // 5
        if dimension in dimensions or area_segments in segments:
            raise RuntimeError(f"{source} contains a duplicate latitude band")
        dimensions.append(dimension)
        segments.add(area_segments)
    return tuple(dimensions)


#: One authoritative pole-to-equator list, stored as ``(height, width)``.
BAND_DIMENSIONS: tuple[BandDimension, ...] = _load_band_dimensions()
BAND_SELECTIONS: tuple[BandSelection, ...] = (
    "portable",
    *(f"{height}x{width}" for height, width in BAND_DIMENSIONS),
)
_DIMENSION_BY_SELECTION = {
    f"{height}x{width}": (height, width) for height, width in BAND_DIMENSIONS
}
_SELECTION_BY_SEGMENTS = {str(width // 5): f"{height}x{width}" for height, width in BAND_DIMENSIONS}


def _canonical_selection(value: str) -> BandSelection | None:
    if value == "portable" or value in _DIMENSION_BY_SELECTION:
        return value
    return _SELECTION_BY_SEGMENTS.get(value)


def _validate_planet_geometry() -> None:
    from flab2bp.dsp import planet

    computed = tuple(
        (band.rows, band.columns)
        for band in sorted(planet.bands(), key=lambda candidate: candidate.area_segments)
    )
    if computed != BAND_DIMENSIONS:
        raise RuntimeError(
            f"latitude_bands.json disagrees with terrestrial planet geometry: {computed!r}"
        )


_validate_planet_geometry()


@dataclass(frozen=True, slots=True)
class BandPolicy:
    """Whether finalization targets portable or one explicit physical band."""

    selection: BandSelection

    def __post_init__(self) -> None:
        canonical = _canonical_selection(self.selection)
        if canonical is None:
            raise ValueError(f"unknown latitude band {self.selection!r}")
        object.__setattr__(self, "selection", canonical)

    @classmethod
    def parse(cls, value: str) -> BandPolicy:
        """Parse one supported CLI/API selection into its canonical dimensions."""
        return cls(value)

    @property
    def explicit_segments(self) -> int | None:
        """The requested area-segment count, or ``None`` for portable selection."""
        if self.selection == "portable":
            return None
        return _DIMENSION_BY_SELECTION[self.selection][1] // 5
