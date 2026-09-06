"""Does trace cost more than 1 % of a build's wall?  Two rules, because one lies.

CP-SAT is nondeterministic under multi-worker, which is the shipping default
(see ab_compare.py:33-36).  "Area byte-identical" therefore cannot be asserted
across independent runs of the shipping configuration, and a gate that asserts
it anyway fails for reasons that have nothing to do with trace.  So:

    RULE P (purity), DETERMINISTIC configuration -- pinned workers, fixed seed,
    islands=1, race off.  Every attempt's (area, belt_tiles) and the whole
    refusal ledger must be EQUAL with trace off and on.  This is the claim that
    the observer is observationally pure.  ("Fixed seed" here is
    `DETERMINISTIC_WORKERS` (layout/base.py): CP-SAT's single-worker mode is
    itself the reproducible configuration -- there is no separate seed
    argument to pin.)

    RULE W (wall), SHIPPING configuration -- default workers, race on,
    --repeat 5, trace-off and trace-on back to back INSIDE each trial so box
    drift hits both equally. PASS iff median(on) <= 1.01 * median(off), per
    cell, with both spreads printed. Spreads that straddle the line are
    NOT SEPARATED, which is a fail: nothing was measured.

Not part of pytest, for the reason ab_compare.py:12-13 gives: a full sweep is
minutes of CP-SAT and the suite stays fast.

    uv run python scripts/trace_overhead.py --purity
    uv run python scripts/trace_overhead.py --wall --repeat 5
    uv run python scripts/trace_overhead.py --wall --cell um60

`vmstat` is captured beside every timing.  This box has 128 cores and is never
idle; the load is I/O wait, so a run is never postponed waiting for an idle
machine -- the contention is RECORDED instead.

RULE W USES THE SHIPPING CLI, NOT AN IN-PROCESS CALL
------------------------------------------------------
Rule W measures the artefact a user actually runs, so each repeat shells out to
the installed ``flab2bp`` console script -- ``--race``, default workers, no
``--workers`` override -- and the trace-on leg adds only ``--trace-jsonl``
(Task 12's CLI flag, the same ``frame_json`` projection the web transport
uses). Two configs that differ by exactly one flag is the fairness property
``ab_compare.py`` already established for A/B strategy comparisons, applied
here to trace on/off instead of to strategies.

RULE P CALLS ``pipeline.build`` DIRECTLY
-----------------------------------------
Purity needs the internal ledger -- every attempt's ``(area, belt_tiles)``,
every refusal's ``(candidate, strategy, reason)``, and the whole
``AttemptProgress`` sequence -- none of which survives a subprocess boundary
intact (the CLI prints only the first five refusals, and never belt_tiles).
So Rule P calls ``pipeline.build(..., search_observer=)`` in-process, wiring up
a real ``SampledObserver`` for the trace-on leg so the comparison exercises the
same observer code the CLI installs, just without the subprocess.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Literal

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp import pipeline  # noqa: E402
from flab2bp.bench.corpus import URL_CORPUS  # noqa: E402
from flab2bp.layout.base import DETERMINISTIC_WORKERS  # noqa: E402
from flab2bp.layout.observe import (  # noqa: E402
    TRACE_SAMPLE_INTERVAL_S,
    SampledObserver,
    SearchEvent,
)
from flab2bp.web.trace import frame_json  # noqa: E402

Verdict = Literal["PASS", "FAIL", "NOT SEPARATED"]
PurityVerdict = Literal["PASS", "FAIL"]

#: One (candidate, strategy, area, belt_tiles) tuple per settled attempt.
AttemptKey = tuple[str, str, int, float]
#: One (candidate, strategy, reason) tuple per refusal.
RefusalKey = tuple[str, str, str]
#: One row per ``AttemptProgress`` callback, in the order fired.
ProgressKey = tuple[int, int, str, str, str, int | None, bool | None, str | None]
Ledger = dict[str, list[Any]]


@dataclass(frozen=True, slots=True)
class Cell:
    """One named gate cell: a corpus entry and the solver budget to run it at."""

    entry_id: str
    budget_s: float


CELLS: dict[str, Cell] = {
    "um60": Cell("universe-matrix", 60.0),
    "qc180": Cell("quantum-chip", 180.0),
    # A conveyor-belt-3 entry (Ruling 5), distinct from um60/qc180 above --
    # casimir-crystal, the smaller of the two conveyor-belt-3 LARGE entries in
    # URL_CORPUS (99 machines vs information-matrix's 101).
    "belt3": Cell("casimir-crystal", 60.0),
}


def _corpus_url(entry_id: str) -> str:
    for entry in URL_CORPUS:
        if entry.url_id == entry_id:
            return entry.url
    raise KeyError(f"no corpus entry {entry_id!r}")


@dataclass(frozen=True, slots=True)
class WallResult:
    """Paired trace-off/trace-on wall times for one cell, ``--repeat`` trials each."""

    cell: str
    off_s: Sequence[float]
    on_s: Sequence[float]
    #: One free-text line per trial (uptime, then the vmstat rows for the
    #: off leg and the on leg), for the evidence file. Empty for a result
    #: built by hand (as the unit tests do).
    context: tuple[str, ...] = field(default_factory=tuple)

    @property
    def median_off(self) -> float:
        return median(self.off_s)

    @property
    def median_on(self) -> float:
        return median(self.on_s)

    @property
    def ratio(self) -> float:
        return self.median_on / self.median_off


def wall_verdict(result: WallResult) -> Verdict:
    """PASS/FAIL/NOT SEPARATED per Ruling 2.

    The "1 % line" is ``1.01 * median(off)``.  If either spread (the observed
    min..max range of that leg's repeats) STRADDLES that line -- has readings
    on both sides of it -- the measurement cannot tell PASS from FAIL and the
    verdict is NOT SEPARATED, regardless of what the medians say.  A spread
    that sits entirely to one side of the line (including the degenerate
    single-value spread of a hand-built result) does not straddle it.
    """
    line = 1.01 * result.median_off
    off_lo, off_hi = min(result.off_s), max(result.off_s)
    on_lo, on_hi = min(result.on_s), max(result.on_s)
    straddles = (off_lo < line < off_hi) or (on_lo < line < on_hi)
    if straddles:
        return "NOT SEPARATED"
    return "PASS" if result.median_on <= line else "FAIL"


def purity_verdict(off: Mapping[str, Any], on: Mapping[str, Any]) -> PurityVerdict:
    """Exact equality of every ledger this gate tracks -- attempts, refusals, progress."""
    return "PASS" if off == on else "FAIL"


def _first_inequality(off: Ledger, on: Ledger) -> str | None:
    """The first differing entry across attempts, then refused, then progress."""
    for key in ("attempts", "refused", "progress"):
        off_list = off.get(key, [])
        on_list = on.get(key, [])
        if len(off_list) != len(on_list):
            return f"{key}: length differs, off={len(off_list)} on={len(on_list)}"
        for index, (off_item, on_item) in enumerate(zip(off_list, on_list, strict=True)):
            if off_item != on_item:
                return f"{key}[{index}]: off={off_item!r} on={on_item!r}"
    return None


@dataclass(frozen=True, slots=True)
class PurityResult:
    """Rule P outcome for one cell: the two ledgers plus the verdict."""

    cell: str
    verdict: PurityVerdict
    off: Ledger
    on: Ledger
    first_inequality: str | None
    #: uptime/vmstat lines bracketing the off leg, then the on leg.
    context: tuple[str, ...] = field(default_factory=tuple)


def _capture_ledger(
    url: str,
    *,
    budget_s: float,
    trace: bool,
    frames: list[str] | None = None,
) -> Ledger:
    """Run one build with the DETERMINISTIC (Rule P) configuration and record its ledger.

    Pinned per Ruling 2: ``DETERMINISTIC_WORKERS``, ``sequence_islands=1``,
    ``race=False``.  ``frames``, when given, is appended to in place by the
    trace-on leg's ``SampledObserver`` sink -- callers use this to report a
    frame count without letting it enter the purity comparison itself (a
    frame count of zero off vs. nonzero on would fail Rule P for having a
    trace at all, not for the search being perturbed).
    """
    progress: list[ProgressKey] = []

    def _on_progress(event: pipeline.AttemptProgress) -> None:
        progress.append(
            (
                event.index,
                event.total,
                event.candidate,
                event.strategy,
                event.phase,
                event.area,
                event.ok,
                event.reason,
            )
        )

    search_observer = None
    if trace:
        started = time.monotonic()
        sink_frames: list[str] = frames if frames is not None else []

        def _sink(event: SearchEvent) -> None:
            seq = len(sink_frames)
            payload = frame_json(seq, round(event.monotonic_s - started, 3), event)
            sink_frames.append(json.dumps(payload))

        search_observer = SampledObserver(sink=_sink, min_interval_s=TRACE_SAMPLE_INTERVAL_S)

    build = pipeline.build(
        url,
        time_budget_s=budget_s,
        workers=DETERMINISTIC_WORKERS,
        sequence_islands=1,
        race=False,
        on_progress=_on_progress,
        search_observer=search_observer,
    )
    attempts: list[AttemptKey] = [
        (
            attempt.candidate,
            attempt.strategy,
            attempt.area,
            float(attempt.placement.stats.get("belt_tiles", float("inf"))),
        )
        for attempt in build.attempts
    ]
    refused: list[RefusalKey] = [
        (failure.candidate, failure.strategy or "", failure.reason) for failure in build.refused
    ]
    return {"attempts": attempts, "refused": refused, "progress": progress}


def purity(cell: str) -> PurityResult:
    """Rule P for one cell: run trace-off and trace-on, deterministically, and compare."""
    c = CELLS[cell]
    url = _corpus_url(c.entry_id)
    pre_off_uptime = _capture_uptime()
    off = _capture_ledger(url, budget_s=c.budget_s, trace=False)
    off_vmstat = _capture_vmstat()
    pre_on_uptime = _capture_uptime()
    on_frames: list[str] = []
    on = _capture_ledger(url, budget_s=c.budget_s, trace=True, frames=on_frames)
    on_vmstat = _capture_vmstat()
    verdict = purity_verdict(off, on)
    context = (
        f"off: uptime={pre_off_uptime!r} vmstat={off_vmstat!r}",
        f"on:  uptime={pre_on_uptime!r} vmstat={on_vmstat!r} frames={len(on_frames)}",
    )
    return PurityResult(
        cell=cell,
        verdict=verdict,
        off=off,
        on=on,
        first_inequality=None if verdict == "PASS" else _first_inequality(off, on),
        context=context,
    )


def _capture_uptime() -> str:
    result = subprocess.run(["uptime"], capture_output=True, text=True, check=False)
    return result.stdout.strip() or f"(uptime failed: {result.stderr.strip()})"


def _capture_vmstat() -> str:
    """Shell ``vmstat 1 2`` and return its second (settled) sample row."""
    result = subprocess.run(["vmstat", "1", "2"], capture_output=True, text=True, check=False)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return f"(vmstat failed: {result.stderr.strip()})"
    return lines[-1]


def _run_cli(url: str, *, budget_s: float, trace_jsonl: Path | None) -> tuple[float, int]:
    """Shell the installed ``flab2bp`` console script; return (wall_s, returncode).

    Shipping configuration: default workers (no ``--workers``), ``--race``.
    The trace-on leg differs from the trace-off leg by exactly one flag,
    ``--trace-jsonl``, so nothing else about the invocation can explain a
    timing difference (the same discipline ``ab_compare.py`` uses for A/B).
    """
    argv = ["uv", "run", "flab2bp", url, "--budget", str(budget_s), "--race", "-o", "/dev/null"]
    if trace_jsonl is not None:
        argv += ["--trace-jsonl", str(trace_jsonl)]
    started = time.perf_counter()
    result = subprocess.run(argv, capture_output=True, text=True, cwd=_ROOT, check=False)
    wall_s = time.perf_counter() - started
    return wall_s, result.returncode


def wall(cell: str, *, repeat: int = 5, evidence_dir: Path | None = None) -> WallResult:
    """Rule W for one cell: ``repeat`` trials, trace-off then trace-on, back to back."""
    c = CELLS[cell]
    url = _corpus_url(c.entry_id)
    off_s: list[float] = []
    on_s: list[float] = []
    context: list[str] = []
    for trial in range(repeat):
        pre_uptime = _capture_uptime()
        off_wall, off_rc = _run_cli(url, budget_s=c.budget_s, trace_jsonl=None)
        off_vmstat = _capture_vmstat()

        trace_path = (
            (evidence_dir / f"{cell}-trial{trial}.jsonl") if evidence_dir is not None else None
        )
        on_wall, on_rc = _run_cli(url, budget_s=c.budget_s, trace_jsonl=trace_path)
        on_vmstat = _capture_vmstat()

        off_s.append(off_wall)
        on_s.append(on_wall)
        context.append(
            f"trial={trial} uptime={pre_uptime!r} off_s={off_wall:.3f} off_rc={off_rc} "
            f"off_vmstat={off_vmstat!r} on_s={on_wall:.3f} on_rc={on_rc} "
            f"on_vmstat={on_vmstat!r}"
        )
    return WallResult(cell=cell, off_s=off_s, on_s=on_s, context=tuple(context))


def _render_purity_markdown(results: list[PurityResult]) -> str:
    lines = ["# Rule P (purity) -- deterministic configuration", ""]
    for r in results:
        lines.append(f"## {r.cell}: {r.verdict}")
        if r.first_inequality:
            lines.append(f"first inequality: {r.first_inequality}")
        lines.append(f"- off attempts: {r.off['attempts']}")
        lines.append(f"- on attempts:  {r.on['attempts']}")
        lines.append(f"- off refused:  {r.off['refused']}")
        lines.append(f"- on refused:   {r.on['refused']}")
        lines.append(f"- off progress: {r.off['progress']}")
        lines.append(f"- on progress:  {r.on['progress']}")
        lines.append("- context:")
        for line in r.context:
            lines.append(f"  - {line}")
        lines.append("")
    return "\n".join(lines)


def _render_wall_markdown(results: list[WallResult]) -> str:
    lines = ["# Rule W (wall) -- shipping configuration, back-to-back trials", ""]
    for r in results:
        verdict = wall_verdict(r)
        lines.append(f"## {r.cell}: {verdict}")
        lines.append(
            f"- median off: {r.median_off:.3f}s  spread [{min(r.off_s):.3f}, {max(r.off_s):.3f}]"
        )
        lines.append(
            f"- median on:  {r.median_on:.3f}s  spread [{min(r.on_s):.3f}, {max(r.on_s):.3f}]"
        )
        lines.append(f"- ratio (on/off): {r.ratio:.4f}")
        lines.append(f"- off_s: {list(r.off_s)}")
        lines.append(f"- on_s:  {list(r.on_s)}")
        lines.append("- per-trial context:")
        for line in r.context:
            lines.append(f"  - {line}")
        lines.append("")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--purity", action="store_true", help="run Rule P on the selected cells")
    ap.add_argument("--wall", action="store_true", help="run Rule W on the selected cells")
    ap.add_argument("--repeat", type=int, default=5, help="Rule W trials per cell (default 5)")
    ap.add_argument(
        "--cell",
        action="append",
        default=None,
        choices=tuple(CELLS),
        help="restrict to this cell; repeatable (default: all three)",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=_ROOT / "docs/superpowers/evidence/2026-09-06-search-trace",
        help="where markdown/JSON evidence is written",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.purity and not args.wall:
        print("nothing to do: pass --purity and/or --wall", file=sys.stderr)
        return 2
    cells = args.cell or list(CELLS)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat(timespec="seconds")

    all_pass = True
    if args.purity:
        purity_results = []
        for cell in cells:
            print(f"purity: {cell}  uptime: {_capture_uptime()}", file=sys.stderr)
            result = purity(cell)
            purity_results.append(result)
            print(f"  {cell}: Rule P {result.verdict}", file=sys.stderr)
            if result.first_inequality:
                print(f"    first inequality: {result.first_inequality}", file=sys.stderr)
            all_pass = all_pass and result.verdict == "PASS"
        out = args.out_dir / f"purity-{started.replace(':', '')}.md"
        out.write_text(_render_purity_markdown(purity_results))
        print(f"purity report -> {out}", file=sys.stderr)

    if args.wall:
        wall_results = []
        for cell in cells:
            print(
                f"wall: {cell} ({args.repeat} trials)  uptime: {_capture_uptime()}",
                file=sys.stderr,
            )
            result = wall(cell, repeat=args.repeat, evidence_dir=args.out_dir)
            wall_results.append(result)
            verdict = wall_verdict(result)
            print(
                f"  {cell}: Rule W {verdict}  median_off={result.median_off:.3f}s "
                f"median_on={result.median_on:.3f}s ratio={result.ratio:.4f}",
                file=sys.stderr,
            )
            all_pass = all_pass and verdict == "PASS"
        out = args.out_dir / f"wall-{started.replace(':', '')}.md"
        out.write_text(_render_wall_markdown(wall_results))
        print(f"wall report -> {out}", file=sys.stderr)

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
