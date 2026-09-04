"""Compare one audit JSONL against a committed baseline, paired by cell.

    uv run python scripts/audit_compare.py BASELINE.jsonl CANDIDATE.jsonl

A cell is ``(strategy, url_id, spec_index)``.  The verdict passes only when
the candidate covers every cell the baseline has, holds the expected number of
rows, has zero REFUSED / INVALID / CRASH rows, its p95 wall per cell is at or
under ``--p95-seconds``, and the geometric mean area ratio over cells clean in
BOTH files is at most ``1 + noise_area``.  ``--noise-area`` defaults to the
1.3% same-arm median measured in ``docs/BACKLOG.md``.

A CELL THE CANDIDATE NEVER RAN IS A FAILURE, not an absence of evidence.  The
comparison used to walk the candidate alone, so a run that died a third of the
way through -- or a file truncated in transit -- presented its surviving rows,
found nothing to disagree with, and printed PASS.  That is the one verdict this
script must never give for work it did not see: the whole point of the gate is
that all 72 cells were tried.  ``--expect-cells`` guards the same property from
the other side, for the case where the baseline is short too.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

CellKey = tuple[str, str, int]


@dataclass(frozen=True)
class Verdict:
    candidate_clean: int
    candidate_refused: int
    candidate_invalid: int
    candidate_crashed: int
    paired_cells: int
    area_ratio: float
    p95_seconds: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return not self.reasons


def _key(row: Mapping[str, object]) -> CellKey:
    return (str(row["strategy"]), str(row["url_id"]), int(str(row["spec_index"])))


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[max(index, 0)]


def compare(
    baseline: Iterable[Mapping[str, object]],
    candidate: Iterable[Mapping[str, object]],
    *,
    noise_area: float,
    p95_seconds: float,
    expect_cells: int | None = None,
    regressions_only: bool = False,
    require_clean: frozenset[str] = frozenset(),
) -> Verdict:
    base_by_key = {_key(row): row for row in baseline}
    candidate_rows = list(candidate)
    candidate_keys = {_key(row) for row in candidate_rows}
    counts: dict[str, int] = {}
    reasons: list[str] = []
    notes: list[str] = []
    log_ratios: list[float] = []
    seconds: list[float] = []
    required_seen: set[str] = set()
    for row in candidate_rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
        seconds.append(float(str(row["seconds"])))
        label = f"{row['strategy']} {row['url_id']}/{row['spec_label']}: {row['detail']}"
        name = f"{row['strategy']}/{row['url_id']}/{row['spec_label']}"
        required_seen.add(name)
        base = base_by_key.get(_key(row))
        if status != "CLEAN":
            if name in require_clean:
                reasons.append(f"NOT CLEAN: {label}")
            elif not regressions_only or status in {"INVALID", "CRASH"}:
                # INVALID and CRASH are never "carried over": the gate demands
                # zero of each outright, and a phase that corrupts a round
                # would show up here first.
                reasons.append(f"{status}: {label}")
            elif base is not None and str(base["status"]) == "CLEAN":
                reasons.append(f"REGRESSION: {label}")
            else:
                notes.append(f"CARRIED: {label}")
            continue
        if base is None or str(base["status"]) != "CLEAN":
            continue
        base_area = float(str(base["area"]))
        cand_area = float(str(row["area"]))
        if base_area > 0 and cand_area > 0:
            log_ratios.append(math.log(cand_area / base_area))
    for key in sorted(base_by_key.keys() - candidate_keys):
        strategy, url_id, _index = key
        missing_label = base_by_key[key]["spec_label"]
        reasons.append(f"MISSING: {strategy} {url_id}/{missing_label}")
    for name in sorted(require_clean - required_seen):
        # A required cell the candidate never attempted cannot be CLEAN; this
        # also catches a mistyped --require-clean name.
        reasons.append(f"MISSING (required): {name}")
    if expect_cells is not None and len(candidate_rows) != expect_cells:
        reasons.append(f"candidate has {len(candidate_rows)} rows, expected {expect_cells}")
    ratio = math.exp(sum(log_ratios) / len(log_ratios)) if log_ratios else 1.0
    p95 = _p95(seconds)
    if ratio > 1.0 + noise_area:
        reasons.append(f"area ratio {ratio:.4f} exceeds 1 + {noise_area}")
    if p95 > p95_seconds:
        reasons.append(f"p95 wall {p95:.1f}s exceeds {p95_seconds}s")
    return Verdict(
        candidate_clean=counts.get("CLEAN", 0),
        candidate_refused=counts.get("REFUSED", 0),
        candidate_invalid=counts.get("INVALID", 0),
        candidate_crashed=counts.get("CRASH", 0),
        paired_cells=len(log_ratios),
        area_ratio=ratio,
        p95_seconds=p95,
        reasons=tuple(reasons),
        notes=tuple(notes),
    )


def _read(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--noise-area", type=float, default=0.013)
    ap.add_argument("--p95-seconds", type=float, default=30.0)
    ap.add_argument(
        "--expect-cells",
        type=int,
        default=72,
        help="rows the candidate must hold; 0 disables the count guard (default: 72)",
    )
    ap.add_argument("--regressions-only", action="store_true")
    ap.add_argument("--require-clean", action="append", default=[])
    args = ap.parse_args(argv)
    verdict = compare(
        _read(args.baseline),
        _read(args.candidate),
        noise_area=args.noise_area,
        p95_seconds=args.p95_seconds,
        expect_cells=args.expect_cells or None,
        regressions_only=args.regressions_only,
        require_clean=frozenset(args.require_clean),
    )
    print(
        f"clean {verdict.candidate_clean}  refused {verdict.candidate_refused}  "
        f"invalid {verdict.candidate_invalid}  crashed {verdict.candidate_crashed}  "
        f"paired {verdict.paired_cells}  area ratio {verdict.area_ratio:.4f}  "
        f"p95 {verdict.p95_seconds:.1f}s"
    )
    for reason in verdict.reasons:
        print(f"  FAIL {reason}")
    for note in verdict.notes:
        print(f"  note {note}")
    print("PASS" if verdict.passed else "FAIL")
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
