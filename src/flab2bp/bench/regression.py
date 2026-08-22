"""Once a winner is picked, the same harness guards it.

Area may drift a little between runs; validity may not drift at all.  An
*improvement* prints a notice rather than failing -- re-baselining is a
deliberate act, not something that happens because a run got lucky.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from flab2bp.bench.types import CellResult

#: Areas above baseline by more than this fail.  Improvements beyond it only
#: print a notice.
AREA_TOLERANCE = 0.02


@dataclass(frozen=True, slots=True)
class Regression:
    class Kind(Enum):
        AREA = "area"
        VALIDITY = "validity"

    kind: Kind
    url_id: str
    message: str


@dataclass(frozen=True, slots=True)
class RegressionResult:
    regressions: tuple[Regression, ...]
    improvements: tuple[str, ...]
    unknown: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.regressions

    def summary(self) -> str:
        lines: list[str] = []
        for r in self.regressions:
            lines.append(f"REGRESSION [{r.kind.value}] {r.url_id}: {r.message}")
        if self.improvements:
            lines.append(
                "Improved beyond tolerance (re-baseline with --bless to record): "
                + ", ".join(self.improvements)
            )
        for url_id in self.unknown:
            lines.append(f"New entry not in baseline, not checked: {url_id}")
        if not lines:
            lines.append("No regressions.")
        return "\n".join(lines)


def _rank(cell: CellResult) -> tuple[int, int]:
    """Sort key: valid beats invalid, then smaller area wins."""
    return (0 if cell.valid else 1, cell.area)


def _best_per_url(cells: Sequence[CellResult]) -> dict[str, CellResult]:
    """The result the pipeline would actually ship for each URL."""
    best: dict[str, CellResult] = {}
    for cell in cells:
        current = best.get(cell.url_id)
        if current is None or _rank(cell) < _rank(current):
            best[cell.url_id] = cell
    return best


def write_baseline(cells: Sequence[CellResult], path: Path) -> None:
    best = _best_per_url(cells)
    payload = {
        "entries": {
            url_id: {
                "area": cell.area,
                "valid": cell.valid,
                "strategy": cell.strategy,
                "candidate": cell.candidate,
            }
            for url_id, cell in sorted(best.items())
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def check_against_baseline(cells: Sequence[CellResult], path: Path) -> RegressionResult:
    payload = json.loads(path.read_text())
    entries: dict[str, dict[str, object]] = payload["entries"]
    best = _best_per_url(cells)

    regressions: list[Regression] = []
    improvements: list[str] = []
    unknown: list[str] = []

    for url_id, cell in sorted(best.items()):
        recorded = entries.get(url_id)
        if recorded is None:
            unknown.append(url_id)
            continue

        was_valid = bool(recorded["valid"])
        if was_valid and not cell.valid:
            regressions.append(
                Regression(
                    Regression.Kind.VALIDITY,
                    url_id,
                    f"was valid, now has {cell.errors} error(s): "
                    + ", ".join(cell.error_checks[:3]),
                )
            )
            continue

        base_area = int(recorded["area"])  # type: ignore[call-overload]
        if not base_area:
            continue
        delta = (cell.area - base_area) / base_area
        if delta > AREA_TOLERANCE:
            regressions.append(
                Regression(
                    Regression.Kind.AREA,
                    url_id,
                    f"area {base_area} -> {cell.area} (+{delta * 100:.1f}%, "
                    f"tolerance {AREA_TOLERANCE * 100:.0f}%)",
                )
            )
        elif delta < -AREA_TOLERANCE:
            improvements.append(f"{url_id} ({base_area} -> {cell.area})")

    return RegressionResult(tuple(regressions), tuple(improvements), tuple(unknown))
