"""Where each strip sits in one sequence-pair permutation.

Backend: a plain dict. The query is a single key over tens of strips on the
hottest Python loop in the solver, which is exactly the case for a plain
dict; a littletable insert per move would cost more than the two
`tuple.index` scans it replaces (measured in Task 23).

`decode_sequence_pair` already builds this index inline
(sequence_pair.py:849-851) and then throws it away. This type is that
pattern promoted, not a new idea.
"""

from __future__ import annotations

from collections.abc import Sequence


class StripPositions:
    """A strip -> position map over one permutation, built once."""

    __slots__ = ("_permutation", "_position")

    def __init__(self, permutation: Sequence[int]) -> None:
        self._permutation = tuple(permutation)
        self._position = {strip: position for position, strip in enumerate(self._permutation)}

    @classmethod
    def of(cls, permutation: Sequence[int]) -> StripPositions:
        """Index one permutation."""
        return cls(permutation)

    def position_of(self, strip: int) -> int:
        """Where ``strip`` sits. Raises ``KeyError`` when it is not present."""
        return self._position[strip]

    def positions_of(self, first: int, second: int) -> tuple[int, int]:
        """Both positions in one call, for the swap that always wants two."""
        position = self._position
        return position[first], position[second]

    def strip_at(self, position: int) -> int:
        """The strip at ``position``."""
        return self._permutation[position]

    def __len__(self) -> int:
        return len(self._permutation)
