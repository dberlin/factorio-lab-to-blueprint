"""Typed latitude-band selection shared by layout entry points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeGuard

type BandSelection = Literal[
    "portable",
    "4",
    "8",
    "16",
    "20",
    "32",
    "40",
    "60",
    "80",
    "100",
    "120",
    "160",
    "200",
]

BAND_SELECTIONS: tuple[BandSelection, ...] = (
    "portable",
    "4",
    "8",
    "16",
    "20",
    "32",
    "40",
    "60",
    "80",
    "100",
    "120",
    "160",
    "200",
)



def _is_band_selection(value: str) -> TypeGuard[BandSelection]:
    return value in BAND_SELECTIONS

@dataclass(frozen=True, slots=True)
class BandPolicy:
    """Whether finalization targets portable or one explicit geometry band."""

    selection: BandSelection

    @classmethod
    def parse(cls, value: str) -> BandPolicy:
        """Parse one supported CLI/API latitude-band selection."""
        if not _is_band_selection(value):
            raise ValueError(f"unknown latitude band {value!r}")
        return cls(value)

    @property
    def explicit_segments(self) -> int | None:
        """The requested segment count, or ``None`` for portable selection."""
        return None if self.selection == "portable" else int(self.selection)
