"""Staked router paths, with the endpoint-adjacency index kept in step.

`_leaning` (freeform.py:10289-10359) rebuilds `touch` and `sole` from every
staked path on every call, once per stranded net inside `_repair`. The paths
themselves are rewritten under it by `_stake` (freeform.py:9916-9938, the
assignment at :9925) and `_unstake` (:9940-9966, the pop at :9962) in the same
phase, which is precisely why the index has to be MAINTAINED rather than
memoized. `into`/`refresh_predecessor` (freeform.py:12495-12511) is the model.

Backend: plain dicts of sets, maintained on stake/unstake. Ruling 2 sends
"grows during a phase" to littletable, and Ruling I-4 overrides that here on one
condition: the write path runs far more often than the read path, so a table
insert per stake would move cost onto the hotter side. The measurement task for
freeform settles it -- and if the dict does not win, the backend changes INSIDE
this module and no caller moves, which is the whole point of the abstraction.

`sole_neighbours` deliberately takes `owner` per call rather than holding it:
`owner` is the router's own cell->net map, rewritten by rip-up outside this
type's knowledge, and a stale copy of it would be a wrong answer rather than a
slow one.

`stake` accepts an empty path without complaint (Ruling P-26): master's
`paths[index] = path` at freeform.py:9925 accepts anything, and Task 26's
conversion of `_stake` calls this with no guard.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

Cell = tuple[int, int, int]


class StakedPaths:
    """Nets currently staked, indexed by the cells beside their endpoints."""

    __slots__ = ("_beside", "_paths", "_positions", "_steps")

    def __init__(self, steps: Sequence[tuple[int, int]]) -> None:
        self._steps = tuple(steps)
        self._paths: dict[int, tuple[Cell, ...]] = {}
        self._positions: dict[int, dict[Cell, int]] = {}
        self._beside: dict[Cell, set[int]] = {}

    def _endpoint_neighbours(self, path: tuple[Cell, ...]) -> list[Cell]:
        if not path:
            return []
        out: list[Cell] = []
        for end in (path[0], path[-1]):
            for dx, dy in self._steps:
                out.append((end[0] + dx, end[1] + dy, end[2]))
        return out

    def stake(self, net: int, path: Sequence[Cell]) -> None:
        """Record ``net`` on ``path``, replacing any path it already held.

        Accepts an empty ``path`` -- master's own assignment does (Ruling P-26).
        """
        if net in self._paths:
            self.unstake(net)
        frozen = tuple(path)
        self._paths[net] = frozen
        self._positions[net] = {cell: position for position, cell in enumerate(frozen)}
        for cell in self._endpoint_neighbours(frozen):
            self._beside.setdefault(cell, set()).add(net)

    def unstake(self, net: int) -> None:
        """Forget ``net`` entirely. A net that is not staked is not an error."""
        path = self._paths.pop(net, None)
        if path is None:
            return
        self._positions.pop(net, None)
        for cell in self._endpoint_neighbours(path):
            holders = self._beside.get(cell)
            if holders is None:
                continue
            holders.discard(net)
            if not holders:
                del self._beside[cell]

    def path(self, net: int) -> tuple[Cell, ...]:
        """The path ``net`` currently holds; empty when it holds none."""
        return self._paths.get(net, ())

    def nets(self) -> tuple[int, ...]:
        """Every staked net, ascending."""
        return tuple(sorted(self._paths))

    def beside(self, cell: Cell) -> frozenset[int]:
        """Nets with an endpoint adjacent to ``cell``."""
        return frozenset(self._beside.get(cell, ()))

    def sole_neighbours(self, net: int, owner: Mapping[Cell, int]) -> frozenset[int]:
        """Nets that are ``net``'s ONLY neighbour at one of its ends.

        Matches freeform.py:10339-10347 exactly: an end whose four steps reach
        exactly one OTHER owner contributes that owner; an end reaching zero or
        two or more contributes nothing.
        """
        path = self._paths.get(net)
        if not path:
            return frozenset()
        out: set[int] = set()
        for end in (path[0], path[-1]):
            near: set[int] = set()
            for dx, dy in self._steps:
                held = owner.get((end[0] + dx, end[1] + dy, end[2]))
                if held is not None and held != net:
                    near.add(held)
            if len(near) == 1:
                out |= near
        return frozenset(out)

    def position_in(self, net: int, cell: Cell) -> int | None:
        """Where ``cell`` sits on ``net``'s path, or ``None``.

        Replaces the "membership test then `.index()`" double scan at
        freeform.py:10442-10453, which walked the same tuple twice.
        """
        positions = self._positions.get(net)
        if positions is None:
            return None
        return positions.get(cell)
