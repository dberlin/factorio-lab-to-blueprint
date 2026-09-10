"""Shared finite-work accounting for constructive transport routing."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from flab2bp.layout import process_resources

WorkKind = Literal[
    "arcs", "augmentations", "candidates", "audit_cells", "predicates", "assignments"
]


class TransportRefusal(RuntimeError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class WorkLimits:
    arcs: int = 100_000
    augmentations: int = 100_000
    candidates: int = 2_000_000
    audit_cells: int = 5_000_000
    predicates: int = 100_000_000
    assignments: int = 100_000


@dataclass
class WorkBudget:
    deadline: float
    limits: WorkLimits = field(default_factory=WorkLimits)
    clock: Callable[[], float] = time.monotonic
    counts: dict[WorkKind, int] = field(default_factory=dict)
    _next_memory_check_s: float = field(default=0.0, init=False)

    def check(self) -> None:
        now = self.clock()
        if now >= self.deadline:
            raise TransportRefusal("DEADLINE", "absolute transport-routing deadline reached")
        if now >= self._next_memory_check_s:
            self._next_memory_check_s = now + 0.05
            if process_resources.usage()[2] > 4 * 1024 * 1024:
                raise TransportRefusal("MEMORY_BOUND", "transport-routing exceeded 4 GiB peak RSS")

    def charge(self, kind: WorkKind, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("work charge must be nonnegative")
        self.check()
        current = self.counts.get(kind, 0)
        if current + amount > getattr(self.limits, kind):
            raise TransportRefusal("POLICY_BOUND", f"{kind} work limit reached at {current}")
        self.counts[kind] = current + amount
