"""Rendering the bake-off.

The matrix is the point.  Strategy B's own designer predicted it is *bimodal* --
excellent or fallback -- while A degrades smoothly.  A single averaged ratio
would hide exactly that, so every cell reports median, worst case, and fallback
rate side by side.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from flab2bp.bench.scoring import compare, geometric_mean
from flab2bp.bench.types import CellResult


@dataclass(frozen=True, slots=True)
class MatrixCell:
    proliferated: bool
    urls: int
    median_ratio: float
    worst_ratio: float
    baseline_fallback_rate: float
    challenger_fallback_rate: float


@dataclass(frozen=True, slots=True)
class MatrixReport:
    baseline: str
    challenger: str
    #: Keyed by whether the candidate is proliferated.
    cells: dict[bool, MatrixCell]


def _is_proliferated(cell: CellResult) -> bool:
    return cell.candidate != "no-proliferator"


def _best(cells: Sequence[CellResult], strategy: str) -> dict[str, CellResult]:
    best: dict[str, CellResult] = {}
    for c in cells:
        if c.strategy != strategy or not c.valid:
            continue
        cur = best.get(c.url_id)
        if cur is None or c.area < cur.area:
            best[c.url_id] = c
    return best


def matrix_report(cells: Sequence[CellResult], baseline: str, challenger: str) -> MatrixReport:
    out: dict[bool, MatrixCell] = {}
    for proliferated in (True, False):
        subset = [c for c in cells if c.power is True and _is_proliferated(c) is proliferated]
        a = _best(subset, baseline)
        b = _best(subset, challenger)
        shared = sorted(set(a) & set(b))
        ratios = [b[u].area / a[u].area for u in shared if a[u].area]

        out[proliferated] = MatrixCell(
            proliferated=proliferated,
            urls=len(shared),
            median_ratio=statistics.median(ratios) if ratios else float("nan"),
            worst_ratio=max(ratios) if ratios else float("nan"),
            baseline_fallback_rate=_fallback_rate(subset, baseline),
            challenger_fallback_rate=_fallback_rate(subset, challenger),
        )
    return MatrixReport(baseline, challenger, out)


def _fallback_rate(cells: Sequence[CellResult], strategy: str) -> float:
    rows = [c for c in cells if c.strategy == strategy]
    if not rows:
        return float("nan")
    return sum(1 for c in rows if c.fallback_used) / len(rows)


def _fmt(value: float) -> str:
    return "--" if value != value else f"{value:.2f}"


def render_markdown(cells: Sequence[CellResult], *, matrix: MatrixReport | None = None) -> str:
    cells = tuple(c for c in cells if c.power is True)
    lines: list[str] = ["# Bake-off", ""]

    lines += ["## Per-cell results", ""]
    lines += [
        "| url | strategy | candidate | area | fill | machines | belts "
        "| sorters | DI | towers | time | status | valid | skipped |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|:--:|---:|",
    ]
    for c in cells:
        verdict = "ok" if c.valid else f"FAIL({c.errors})"
        if c.valid and c.skipped_checks:
            verdict = "ok*"
        lines.append(
            f"| {c.url_id} | {c.strategy} | {c.candidate} | {c.area} | "
            f"{c.packing_efficiency:.2f} | {c.machines} | {c.belt_tiles} | "
            f"{c.sorters} | {c.direct_inserts} | {c.towers} | "
            f"{c.solve_seconds:.2f}s | {c.solver_status} | {verdict} | "
            f"{len(c.skipped_checks)} |"
        )

    lines += [
        "",
        "`ok*` means every check that ran passed, but some checks were "
        "**skipped** and are therefore neither passed nor failed. A build with "
        "skipped throughput checks has not been verified for throughput.",
        "",
    ]

    skipped = sorted({s for c in cells for s in c.skipped_checks})
    if skipped:
        lines += [
            f"Checks skipped across this run ({len(skipped)}): "
            + ", ".join(f"`{s}`" for s in skipped),
            "",
        ]

    lines += _winning_candidates(cells)

    if matrix is not None:
        lines += _render_matrix(matrix)

    lines += _render_verdict(cells, matrix)
    return "\n".join(lines)


def _winning_candidates(cells: Sequence[CellResult]) -> list[str]:
    """Which candidate actually won, per URL per strategy.

    If every strategy always picks the same candidate, the whole multi-candidate
    machinery is dead weight -- and that should be measured, not assumed.
    """
    lines = [
        "## Winning candidate per URL",
        "",
        "| url | strategy | candidate | area |",
        "|---|---|---|---:|",
    ]
    best: dict[tuple[str, str], CellResult] = {}
    for c in cells:
        if not c.valid:
            continue
        key = (c.url_id, c.strategy)
        cur = best.get(key)
        if cur is None or c.area < cur.area:
            best[key] = c
    for (url_id, strategy), c in sorted(best.items()):
        lines.append(f"| {url_id} | {strategy} | {c.candidate} | {c.area} |")

    tally = Counter(c.candidate for c in best.values())
    lines += ["", f"Candidate win tally: {dict(tally)}"]
    if len(tally) == 1 and len(best) > 1:
        lines.append(
            "**Only one candidate ever wins.** The multi-candidate frontier is "
            "currently dead weight and could be dropped."
        )
    lines.append("")
    return lines


def _render_matrix(matrix: MatrixReport) -> list[str]:
    lines = [
        f"## Matrix: {matrix.challenger} vs {matrix.baseline}",
        "",
        "Ratios are challenger/baseline area; below 1.00 means the challenger is "
        "denser. Worst case and fallback rate are shown because a bimodal "
        "strategy and a smoothly-degrading one can share a median.",
        "",
        "| proliferated | urls | median | worst | "
        f"{matrix.baseline} fallback | {matrix.challenger} fallback |",
        "|:--:|---:|---:|---:|---:|---:|",
    ]
    for proliferated, cell in sorted(matrix.cells.items(), reverse=True):
        lines.append(
            f"| {'Y' if proliferated else 'N'} | {cell.urls} | "
            f"{_fmt(cell.median_ratio)} | "
            f"{_fmt(cell.worst_ratio)} | "
            f"{_fmt(cell.baseline_fallback_rate)} | "
            f"{_fmt(cell.challenger_fallback_rate)} |"
        )
    lines.append("")
    return lines


def _render_verdict(cells: Sequence[CellResult], matrix: MatrixReport | None) -> list[str]:
    baseline = matrix.baseline if matrix else "sequence-pair"
    challenger = matrix.challenger if matrix else "freeform"
    verdict = compare(cells, baseline, challenger)
    lines = ["## Verdict", "", verdict.summary(), ""]

    ratios = [c.area for c in cells if c.strategy == baseline and c.valid]
    if ratios:
        lines.append(f"Geometric-mean area ratio: {geometric_mean([verdict.area_ratio]):.3f}")
    lines += [
        "",
        "A valid placement is not a working factory: the validator checks "
        "geometry, reach, continuity and capacity, not whether DSP will accept "
        "every connection. Paste-testing in game remains the final check.",
        "",
    ]
    return lines


def write_results(cells: Sequence[CellResult], path: Path, *, seed: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seed": seed,
        "results": [c.to_json() for c in cells],
    }
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
