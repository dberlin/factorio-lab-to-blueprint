"""Compatible incumbent retention; temporary assumptions never become exclusions."""

from __future__ import annotations

from .budget import WorkBudget
from .cnf import FactorCNF


class Neighborhood:
    def __init__(self, budget: WorkBudget) -> None:
        self.budget: WorkBudget = budget
        self.best_conflicts: int | None = None
        self.retained: dict[int, tuple[int, int]] = {}
        self.assumptions: list[int] = []
        self._owners: dict[int, int] = {}

    def _rebuild(self) -> None:
        self.budget.charge("predicates", 6 * len(self.retained))
        self.assumptions = []
        self._owners = {}
        for domain, literals in self.retained.items():
            self.assumptions.extend(literals)
            for literal in literals:
                self._owners[literal] = domain

    def consider(
        self, selected: list[int], conflicts: list[tuple[int, int]], factors: FactorCNF
    ) -> None:
        self.budget.charge("predicates", 2)
        if self.best_conflicts is not None and len(conflicts) >= self.best_conflicts:
            return
        count = len(selected)
        self.budget.charge("predicates", count)
        adjacent: list[set[int]] = [set() for _ in selected]
        for left, right in conflicts:
            self.budget.charge("predicates", 4)
            adjacent[left].add(right)
            adjacent[right].add(left)
        self.budget.charge("predicates", count * max(1, count.bit_length()))
        order = sorted(range(count), key=lambda domain: (len(adjacent[domain]), domain))
        blocked: set[int] = set()
        self.retained = {}
        for domain in order:
            self.budget.charge("predicates")
            if domain in blocked:
                continue
            self.budget.charge("predicates", 5 + len(adjacent[domain]))
            combo, height = divmod(selected[domain], len(factors.height[domain]))
            self.retained[domain] = factors.xy[domain][combo], factors.height[domain][height]
            blocked.update(adjacent[domain])
        self.best_conflicts = len(conflicts)
        self._rebuild()

    def relax(self, core: list[int] | None) -> int:
        """Strictly release whole paths; unrestricted UNSAT must be checked separately."""
        self.budget.charge("predicates")
        if not self.retained:
            return 0
        if core:
            released: set[int] = set()
            for literal in core:
                self.budget.charge("predicates", 2)
                if literal not in self._owners:
                    raise AssertionError("native core contains a non-assumed literal")
                released.add(self._owners[literal])
        else:
            self.budget.charge("predicates", len(self.retained))
            released = set(self.retained)
        for domain in released:
            self.budget.charge("predicates")
            del self.retained[domain]
        self._rebuild()
        return len(released)
