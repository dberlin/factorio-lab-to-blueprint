"""The record of one bake-off cell.

One ``CellResult`` per ``(url, candidate, strategy, power)`` combination.  Every
field is measured by the harness rather than reported by the strategy -- a
strategy that reports its own numbers is marking its own homework.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


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
