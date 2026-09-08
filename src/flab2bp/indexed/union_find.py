"""Disjoint sets with path compression and union by rank.

freeform.py writes this structure from scratch three times, at HEAD:

- net-role grouping inside `_prepared_routing_lower_bound` (around :8955-9017):
  keys are `NetId`, pre-registered for every net before any union; `find` uses
  grandparent path-halving and would `KeyError` on an unseen key (never
  exercised, since every id is pre-registered); `union` has no rank and always
  keeps the FIRST argument's root. Its result only feeds a `max`/`sum` over
  `component_floors`, so which id survives as root never reaches output.
- `_connect_short_cuts` (around :16008-16113) and `_join_shard_islands`
  (around :16115-16233): keys are synthetic `("s"|"d", int)` pairs and belt
  `int`s; both use the same lazy `parent.setdefault(k, k)` plus path-halving,
  and both union inline with no rank -- the SECOND argument's root always
  survives. Both then sort islands by a `Fraction` balance with the
  union-find root as an explicit, comment-documented tie-breaker for exact
  balance ties ("root order as the deterministic tie-breaker" -- freeform.py
  near :16162). That is the one place root *identity*, not just set
  membership, can reach output, and it is unreachable by rank-based union
  standing in for their unranked one except by coincidence. Those callers use
  ``union(..., keep_right=True)`` to preserve their exact historical roots.

Backend: plain dict-backed arrays, not `networkx.utils.UnionFind` -- that
pulls a graph library into freeform's hot path for a structure with no query
to index, and is slower than a short array implementation for this size.

`groups()` is ordered -- first-insertion order between groups, insertion
order within one -- because grouped output can reach a routing decision, and
an arbitrary order would make that decision non-reproducible (Ruling I-6).
"""

from __future__ import annotations

from collections.abc import Hashable


class UnionFind:
    """Merge-and-query disjoint sets over arbitrary hashable nodes."""

    __slots__ = ("_order", "_parent", "_rank")

    def __init__(self) -> None:
        self._parent: dict[Hashable, Hashable] = {}
        self._rank: dict[Hashable, int] = {}
        self._order: list[Hashable] = []

    def find(self, node: Hashable) -> Hashable:
        """The representative of ``node``'s set, creating the node if new."""
        parent = self._parent
        if node not in parent:
            parent[node] = node
            self._rank[node] = 0
            self._order.append(node)
            return node
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(self, left: Hashable, right: Hashable, *, keep_right: bool = False) -> bool:
        """Merge sets, optionally retaining the right root for ordered consumers."""
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return False
        if keep_right:
            self._parent[left_root] = right_root
            self._rank[right_root] = max(self._rank[right_root], self._rank[left_root] + 1)
            return True
        if self._rank[left_root] < self._rank[right_root]:
            left_root, right_root = right_root, left_root
        self._parent[right_root] = left_root
        if self._rank[left_root] == self._rank[right_root]:
            self._rank[left_root] += 1
        return True

    def connected(self, left: Hashable, right: Hashable) -> bool:
        """Whether two nodes share a set."""
        return self.find(left) == self.find(right)

    def groups(self) -> tuple[tuple[Hashable, ...], ...]:
        """Every set, in first-insertion order, members in insertion order."""
        buckets: dict[Hashable, list[Hashable]] = {}
        for node in self._order:
            buckets.setdefault(self.find(node), []).append(node)
        seen: set[Hashable] = set()
        out: list[tuple[Hashable, ...]] = []
        for node in self._order:
            root = self.find(node)
            if root in seen:
                continue
            seen.add(root)
            out.append(tuple(buckets[root]))
        return tuple(out)
