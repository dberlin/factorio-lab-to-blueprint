"""Staked router paths, with the endpoint-adjacency index kept in step.

`_leaning` (freeform.py:10289-10359) rebuilds `touch` and `sole` from every
staked path on every call, once per stranded net inside `_repair`. The paths
themselves are rewritten under it by `_stake` (freeform.py:9916-9938, the
assignment at :9925) and `_unstake` (:9940-9966, the pop at :9962) in the same
phase, which is precisely why the index has to be MAINTAINED rather than
memoized. `into`/`refresh_predecessor` (freeform.py:12495-12511) is the model.

Backend: plain dicts of sets, maintained on stake/unstake. The indexed domain
owns write/read consistency; callers do not reproduce its adjacency scans.

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

    __slots__ = (
        "_beside",
        "_linked_heads",
        "_next_order",
        "_order",
        "_paths",
        "_positions",
        "_steps",
    )

    def __init__(self, steps: Sequence[tuple[int, int]]) -> None:
        self._steps = tuple(steps)
        self._paths: dict[int, tuple[Cell, ...]] = {}
        self._positions: dict[int, dict[Cell, int]] = {}
        self._beside: dict[Cell, set[int]] = {}
        self._order: dict[int, int] = {}
        self._next_order = 0
        self._linked_heads: dict[int, Cell] = {}

    def _endpoint_neighbours(self, path: tuple[Cell, ...]) -> list[Cell]:
        if not path:
            return []
        out: list[Cell] = []
        for end in (path[0], path[-1]):
            for dx, dy in self._steps:
                out.append((end[0] + dx, end[1] + dy, end[2]))
        return out

    def stake(self, net: int, path: Sequence[Cell], *, linked_head: bool = False) -> None:
        """Record ``net`` on ``path``, replacing any path it already held.

        Accepts an empty ``path`` -- master's own assignment does (Ruling P-26).
        """
        order = self._order.get(net)
        if net in self._paths:
            self.unstake(net)
        frozen = tuple(path)
        if order is None:
            order = self._next_order
            self._next_order += 1
        self._order[net] = order
        self._paths[net] = frozen
        positions: dict[Cell, int] = {}
        for position, cell in enumerate(frozen):
            positions.setdefault(cell, position)
        self._positions[net] = positions
        if linked_head and frozen:
            self._linked_heads[net] = frozen[0]
        for cell in self._endpoint_neighbours(frozen):
            self._beside.setdefault(cell, set()).add(net)

    def unstake(self, net: int) -> None:
        """Forget ``net`` entirely. A net that is not staked is not an error."""
        path = self._paths.pop(net, None)
        if path is None:
            return
        self._positions.pop(net, None)
        self._order.pop(net, None)
        self._linked_heads.pop(net, None)
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

    def beside_in_scan_order(self, cell: Cell) -> tuple[int, ...]:
        """Match iteration of the former freshly rebuilt set of neighbours.

        Deletions change a maintained set's table shape. Reinsert just this
        cell's neighbours in live path order so capped repair visits the same
        victims, without rebuilding adjacency from all paths.
        """
        touched: set[int] = set()
        for net in sorted(self._beside.get(cell, ()), key=self._order.__getitem__):
            touched.add(net)
        return tuple(touched)

    def linked_heads(self) -> frozenset[Cell]:
        """Heads belonging to paths that selected a source junction tap."""
        return frozenset(self._linked_heads.values())

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
