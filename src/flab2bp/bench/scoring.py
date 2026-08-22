"""Declaring a winner.

Lexicographic -- validity, then density, then time -- and deliberately not a
weighted sum, because a weighted sum invites tuning the weights until the
preferred answer wins.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from flab2bp.bench.types import CellResult

#: Below this relative margin the two strategies are declared equivalent on
#: density and the tie-break moves on to time.  Area differences smaller than a
#: few percent are within the noise of arbitrary packing decisions.
DENSITY_DEADBAND = 0.03


def geometric_mean(values: Iterable[float]) -> float:
    """Geometric mean, because area ratios are multiplicative.

    An arithmetic mean would let one enormous stress case dominate twelve
    results.  Empty input is 1.0 -- the neutral ratio.
    """
    vals = [v for v in values if v > 0]
    if not vals:
        return 1.0
    return math.exp(statistics.fmean(math.log(v) for v in vals))


@dataclass(frozen=True, slots=True)
class Verdict:
    class Reason(Enum):
        VALIDITY = "validity"
        DENSITY = "density"
        TIME = "time"
        INCOMPARABLE = "incomparable"

    winner: str | None
    reason: Reason
    area_ratio: float
    comparable: int
    baseline: str
    challenger: str
    baseline_valid: int
    challenger_valid: int
    baseline_median_seconds: float
    challenger_median_seconds: float

    def summary(self) -> str:
        if self.reason is Verdict.Reason.INCOMPARABLE:
            return (
                f"No comparison possible: {self.comparable} URL(s) where both "
                f"{self.baseline} and {self.challenger} produced a valid placement."
            )
        pct = (1.0 - self.area_ratio) * 100.0
        direction = "smaller" if pct > 0 else "larger"
        return (
            f"{self.winner} wins on {self.reason.value}. "
            f"{self.challenger} area is {abs(pct):.1f}% {direction} than "
            f"{self.baseline} (geometric mean over {self.comparable} URLs)."
        )


def _best_per_url(cells: Sequence[CellResult], strategy: str) -> dict[str, CellResult]:
    """The best valid candidate per URL, which is what the pipeline would ship."""
    best: dict[str, CellResult] = {}
    for cell in cells:
        if cell.strategy != strategy or not cell.valid:
            continue
        current = best.get(cell.url_id)
        if current is None or cell.area < current.area:
            best[cell.url_id] = cell
    return best


def compare(cells: Sequence[CellResult], baseline: str, challenger: str) -> Verdict:
    """Rank ``challenger`` against ``baseline``.

    The ratio is computed only over URLs where BOTH produced a valid placement;
    comparing a strategy's successes against another's failures would flatter
    whichever one gave up more often.
    """
    a = _best_per_url(cells, baseline)
    b = _best_per_url(cells, challenger)
    shared = sorted(set(a) & set(b))

    a_times = [c.solve_seconds for c in a.values()]
    b_times = [c.solve_seconds for c in b.values()]
    a_median = statistics.median(a_times) if a_times else math.inf
    b_median = statistics.median(b_times) if b_times else math.inf

    ratio = geometric_mean([b[u].area / a[u].area for u in shared if a[u].area])

    def verdict(winner: str | None, reason: Verdict.Reason) -> Verdict:
        return Verdict(
            winner=winner,
            reason=reason,
            area_ratio=ratio,
            comparable=len(shared),
            baseline=baseline,
            challenger=challenger,
            baseline_valid=len(a),
            challenger_valid=len(b),
            baseline_median_seconds=a_median,
            challenger_median_seconds=b_median,
        )

    # A strategy that never ran at all is incomparable, NOT a validity loser --
    # Strategy B may simply not be implemented yet, and reporting that as a win
    # for A would be meaningless.
    ran = {c.strategy for c in cells}
    if baseline not in ran or challenger not in ran:
        return verdict(None, Verdict.Reason.INCOMPARABLE)

    # 1. Validity. A dense invalid blueprint is worth nothing.
    if len(a) != len(b):
        return verdict(baseline if len(a) > len(b) else challenger, Verdict.Reason.VALIDITY)

    if not shared:
        return verdict(None, Verdict.Reason.INCOMPARABLE)

    # 2. Density, but only outside the deadband.
    if abs(1.0 - ratio) > DENSITY_DEADBAND:
        return verdict(challenger if ratio < 1.0 else baseline, Verdict.Reason.DENSITY)

    # 3. Time. Measured but never the primary ranking -- it is the least
    #    reproducible number in the report.
    return verdict(baseline if a_median <= b_median else challenger, Verdict.Reason.TIME)
