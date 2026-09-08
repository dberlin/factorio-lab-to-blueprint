"""Where each strip identity sits in one immutable ordered sequence.

Backend: a plain dict. The query is a single key over tens of strips on the
hottest Python loop in the solver, which is exactly the case for a plain
dict; measurements at each converted call site must include construction.

`decode_sequence_pair` already builds this index inline
(sequence_pair.py:849-851) and then throws it away. This type is that
pattern promoted, not a new idea.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence


class StripPositions[T: Hashable]:
    """A strip -> first position map, built once over immutable identities."""

    __slots__ = ("_permutation", "_position")

    def __init__(self, permutation: Sequence[T]) -> None:
        self._permutation = tuple(permutation)
        self._position: dict[T, int] = {}
        for position, strip in enumerate(self._permutation):
            self._position.setdefault(strip, position)

    @classmethod
    def of(cls, permutation: Sequence[T]) -> StripPositions[T]:
        """Index one permutation."""
        return cls(permutation)

    def position_of(self, strip: T) -> int:
        """Where ``strip`` sits. Raises ``KeyError`` when it is not present."""
        return self._position[strip]

    def positions_of(self, first: T, second: T) -> tuple[int, int]:
        """Both positions in one call, for the swap that always wants two."""
        position = self._position
        return position[first], position[second]

    def strip_at(self, position: int) -> T:
        """The strip at ``position``."""
        return self._permutation[position]

    def __len__(self) -> int:
        return len(self._permutation)
