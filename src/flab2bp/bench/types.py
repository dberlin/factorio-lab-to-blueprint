"""The record of one bake-off cell.

One ``CellResult`` per ``(url, candidate, strategy, power)`` combination.  Every
field is measured by the harness rather than reported by the strategy -- a
strategy that reports its own numbers is marking its own homework.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class CellResultJson(TypedDict):
    strategy: str
    url_id: str
    candidate: str
    power: bool
    area: int
    used_tiles: int
    width: int
    height: int
    machines: int
    belt_tiles: int
    sorters: int
    direct_inserts: int
    towers: int
    altitude_levels: int
    solve_seconds: float
    hit_time_budget: bool
    fallback_used: bool
    solver_status: str
    valid: bool
    errors: int
    warnings: int
    skipped_checks: tuple[str, ...]
    error_checks: tuple[str, ...]
    checks_run: int


@dataclass(frozen=True, slots=True)
class CellResult:
    strategy: str
    url_id: str
    candidate: str
    power: bool

    # density
    area: int
    used_tiles: int
    width: int
    height: int

    # composition
    machines: int
    belt_tiles: int
    sorters: int
    direct_inserts: int
    towers: int
    altitude_levels: int

    # cost
    solve_seconds: float
    hit_time_budget: bool
    fallback_used: bool
    solver_status: str

    # correctness
    valid: bool
    errors: int
    warnings: int
    #: Checks that could NOT be evaluated.  Reported prominently, because a
    #: build that skipped its throughput checks is not a build that passed them.
    skipped_checks: tuple[str, ...] = ()
    #: Which checks actually produced errors, so a failure is diagnosable from
    #: the report alone.
    error_checks: tuple[str, ...] = ()
    checks_run: int = 0

    @property
    def packing_efficiency(self) -> float:
        """``used_tiles / area``.

        Reported next to area so a strategy that wins the bounding box purely by
        being a long thin ribbon is visible as exactly that.
        """
        return self.used_tiles / self.area if self.area else 0.0

    @property
    def verified(self) -> bool:
        """Valid *and* nothing important went unchecked.

        ``valid`` alone overstates confidence: it means "no check that ran
        failed", which for a build with no ``BuildSpec`` excludes every
        throughput check.
        """
        return self.valid and not self.skipped_checks

    def to_json(self) -> CellResultJson:
        return {
            "strategy": self.strategy,
            "url_id": self.url_id,
            "candidate": self.candidate,
            "power": self.power,
            "area": self.area,
            "used_tiles": self.used_tiles,
            "width": self.width,
            "height": self.height,
            "machines": self.machines,
            "belt_tiles": self.belt_tiles,
            "sorters": self.sorters,
            "direct_inserts": self.direct_inserts,
            "towers": self.towers,
            "altitude_levels": self.altitude_levels,
            "solve_seconds": self.solve_seconds,
            "hit_time_budget": self.hit_time_budget,
            "fallback_used": self.fallback_used,
            "solver_status": self.solver_status,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "skipped_checks": self.skipped_checks,
            "error_checks": self.error_checks,
            "checks_run": self.checks_run,
        }


@dataclass(frozen=True, slots=True)
class Metrics:
    """Geometry and composition measured from a ``Placement``."""

    area: int
    used_tiles: int
    width: int
    height: int
    machines: int
    belt_tiles: int
    sorters: int
    direct_inserts: int
    towers: int
    altitude_levels: int

    @property
    def packing_efficiency(self) -> float:
        return self.used_tiles / self.area if self.area else 0.0
