"""The ordered routing-path authority and its live endpoint/position indexes.

Mapping reads expose immutable paths in stake insertion order. Only ``stake``
and ``unstake`` mutate the live collection; ordered immutable snapshots restore
all path-derived indexes together. World occupancy and route hints remain the
enclosing route transaction's responsibility.

``sole_neighbours`` takes the router's current cell owner per query rather than
holding a stale copy. Empty paths are staked entries, distinct from absent keys.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

Cell = tuple[int, int, int]
type StakedPathSnapshot = tuple[tuple[int, tuple[Cell, ...], bool], ...]


class StakedPaths(Mapping[int, tuple[Cell, ...]]):
    """Nets currently staked, in insertion order, with indexed endpoint queries."""

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

    def __getitem__(self, net: int) -> tuple[Cell, ...]:
        return self._paths[net]

    def __iter__(self) -> Iterator[int]:
        return iter(self._paths)

    def __len__(self) -> int:
        return len(self._paths)

    def snapshot(self) -> StakedPathSnapshot:
        """Freeze ordered paths and linked-head membership without copying cells."""
        return tuple((net, path, net in self._linked_heads) for net, path in self._paths.items())

    def restore(self, snapshot: StakedPathSnapshot) -> None:
        """Replace the live state and every derived index with one saved order."""
        self._paths.clear()
        self._positions.clear()
        self._beside.clear()
        self._order.clear()
        self._linked_heads.clear()
        self._next_order = 0
        for net, path, linked_head in snapshot:
            self.stake(net, path, linked_head=linked_head)

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

        Replacing a stake retains its position; removing and reinserting it
        appends it. An empty path remains a present mapping entry.
        """
        previous = self._paths.get(net)
        if previous is not None:
            self._forget_indexes(net, previous)
        else:
            self._order[net] = self._next_order
            self._next_order += 1
        frozen = tuple(path)
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
        del self._order[net]
        self._forget_indexes(net, path)

    def _forget_indexes(self, net: int, path: tuple[Cell, ...]) -> None:
        self._positions.pop(net, None)
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
