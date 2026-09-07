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

RULE W FIX ROUND 1: THE CLI'S ``--trace-jsonl`` IS INERT UNDER ``--race``
---------------------------------------------------------------------------
The first version of this harness shelled out to the ``flab2bp`` console
script for Rule W, on the theory that the CLI is "the shipping artefact."
That measured nothing: ``cli.py`` never threads a ``trace_queue`` through to
``pipeline.build``, so under ``--race`` every raced arm runs with tracing
structurally disabled regardless of ``--trace-jsonl`` -- confirmed by all 15
trace-on trials of that first sweep producing a 0-byte JSONL file, and by an
isolated 2-second repro (serial: 8 frames; ``--race``: 0 frames). A wall-clock
comparison between two identical, untraced runs is not a measurement of
observer cost; it is noise wearing a ratio.

Rule W now drives ``pipeline.build`` directly, in the raced shipping
configuration (``race=True``, default workers), wiring up a real
``multiprocessing.Queue`` plus a ``web.trace.TraceCollector`` to drain it --
the exact mechanism ``web/jobs.py``'s ``Builder._run`` uses for a live web
build (construct the queue, start the collector's daemon drain thread, hand
``collector.observer`` to ``search_observer`` and the queue itself to
``trace_queue``, then ``collector.stop()`` after the build settles). This is
"the shipping artefact minus argument parsing": the real code path a raced,
traced build actually takes, without the CLI's now-known-broken wiring in the
way. See ``_run_direct`` and FIX 1 below.

FIX 1: A HARNESS THAT CANNOT DETECT ITS OWN NO-OP MEASURES NOTHING
---------------------------------------------------------------------
The first round's real defect was not just the CLI gap -- it was that the
*harness* could not tell the difference between "tracing cost nothing" and
"tracing never ran," and reported three plausible-looking ratios either way.
``_require_frames_captured`` is now a hard precondition on every trace-on leg:
zero frames raises ``TraceNotCapturedError`` and that leg's timing is refused,
never silently accepted into a median.

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
import multiprocessing
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Literal, cast

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp import pipeline  # noqa: E402
from flab2bp.bench.corpus import entry as corpus_entry  # noqa: E402
from flab2bp.layout.base import DETERMINISTIC_WORKERS  # noqa: E402
from flab2bp.layout.observe import (  # noqa: E402
    TRACE_SAMPLE_INTERVAL_S,
    SampledObserver,
    SearchEvent,
)
from flab2bp.layout.observe_channel import TRACE_QUEUE_MAXSIZE  # noqa: E402
from flab2bp.web.trace import TraceCollector, TraceRing, frame_json  # noqa: E402

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
    return corpus_entry(entry_id).url


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
    #: Frames captured on each trial's trace-on leg, in trial order -- proof
    #: (per FIX 1) that every accepted ``on_s`` reading actually traced
    #: something. Empty for a result built by hand.
    on_frames: tuple[int, ...] = field(default_factory=tuple)

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


class TraceNotCapturedError(RuntimeError):
    """A trace-on leg captured zero frames -- the observer never fired.

    Fix round 1's whole lesson: a wall-clock ratio computed from a trace-on
    leg that traced nothing is not a measurement of trace cost, it is two
    identical runs compared against each other. This must never be accepted
    into a median silently.
    """


def _require_frames_captured(frame_count: int, *, cell: str, leg: str) -> None:
    """Hard precondition on every trace-on leg: refuse a leg that traced nothing.

    Not a warning -- a raised exception, so a caller cannot forget to check it
    and cannot average it away. There is no legitimate reason for a
    correctly-wired trace-on leg to produce zero frames over a multi-second
    budget: ``ALWAYS_SAMPLE`` alone (incumbent, composed) fires at least once
    per settled attempt.
    """
    if frame_count <= 0:
        raise TraceNotCapturedError(
            f"{cell}: {leg}'s trace-on leg captured 0 frames -- the observer "
            "never fired, so this leg's timing cannot be used to measure "
            "trace overhead. Refusing to accept it into Rule W's median."
        )


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


def _run_direct(
    url: str,
    *,
    budget_s: float,
    trace: bool,
    evidence_path: Path | None = None,
) -> tuple[float, int]:
    """Run ``pipeline.build`` in the raced shipping configuration; return (wall_s, frame_count).

    Mirrors ``web/jobs.py``'s ``Builder._run`` exactly: a spawn-context
    ``multiprocessing.Queue`` plus a ``TraceCollector`` draining it on a
    background thread, so a raced arm's search events reach this process the
    same way the real web consumer receives them (Task 8 fix round 1's
    ``trace_queue`` contract). ``search_observer=None, trace_queue=None`` for
    the trace-off leg is the CLI's own off-by-default shape -- one ``is None``
    per call site, nothing constructed.

    ``wall_s`` covers only the ``pipeline.build`` call itself, not collector
    teardown afterwards: a live web build is "done," from a caller's point of
    view, the instant ``pipeline.build`` returns, and charging the on-leg for
    its own cleanup would be exactly the kind of asymmetry Rule W exists to
    rule out.

    ``frame_count`` is ``collector._seq`` after ``collector.stop()`` -- the
    total number of events the collector actually turned into a frame, from
    either source (`` _pending``, the in-process/serial path, or ``queue``,
    the raced/child path), which is the same counter a live web build's
    frames are numbered by. It is exactly 0 for a trace-off leg (no collector
    at all -- not "traced but empty").
    """
    collector: TraceCollector | None = None
    trace_queue: object | None = None
    search_observer: SampledObserver | None = None
    if trace:
        trace_queue = multiprocessing.get_context("spawn").Queue(maxsize=TRACE_QUEUE_MAXSIZE)
        collector = TraceCollector(TraceRing(), started_at=time.monotonic(), queue=trace_queue)
        collector.start()
        search_observer = collector.observer

    started = time.perf_counter()
    try:
        pipeline.build(
            url,
            time_budget_s=budget_s,
            race=True,
            search_observer=search_observer,
            trace_queue=trace_queue,
        )
    finally:
        wall_s = time.perf_counter() - started

    frame_count = 0
    if collector is not None:
        collector.stop()
        frame_count = collector._seq  # noqa: SLF001 -- the harness's own frame count, by design
        if evidence_path is not None:
            # `-1`, not `0`: `since`'s cursor is EXCLUSIVE (web/trace.py), so a
            # `0` cursor drops frame `seq=0` from every evidence file (fix
            # round, Minor 5). `-1` is the sentinel used everywhere else a
            # caller wants every frame the ring still holds.
            frames, _next = collector.ring.since(-1, limit=collector.ring.max_frames)
            evidence_path.write_text("\n".join(json.dumps(frame) for frame in frames) + "\n")
    if trace_queue is not None:
        cast(Any, trace_queue).cancel_join_thread()
        cast(Any, trace_queue).close()
    return wall_s, frame_count


def wall(cell: str, *, repeat: int = 5, evidence_dir: Path | None = None) -> WallResult:
    """Rule W for one cell: ``repeat`` trials, trace-off then trace-on, back to back.

    Raises :class:`TraceNotCapturedError` (FIX 1) the instant any trace-on leg
    captures zero frames -- that trial's timing is refused outright rather
    than folded into the median silently.
    """
    c = CELLS[cell]
    url = _corpus_url(c.entry_id)
    off_s: list[float] = []
    on_s: list[float] = []
    on_frames: list[int] = []
    context: list[str] = []
    for trial in range(repeat):
        pre_uptime = _capture_uptime()
        off_wall, _off_frames = _run_direct(url, budget_s=c.budget_s, trace=False)
        off_vmstat = _capture_vmstat()

        evidence_path = (
            (evidence_dir / f"{cell}-trial{trial}-on.jsonl") if evidence_dir is not None else None
        )
        on_wall, frame_count = _run_direct(
            url, budget_s=c.budget_s, trace=True, evidence_path=evidence_path
        )
        _require_frames_captured(frame_count, cell=cell, leg=f"trial{trial}")
        on_vmstat = _capture_vmstat()

        off_s.append(off_wall)
        on_s.append(on_wall)
        on_frames.append(frame_count)
        context.append(
            f"trial={trial} uptime={pre_uptime!r} off_s={off_wall:.3f} "
            f"off_vmstat={off_vmstat!r} on_s={on_wall:.3f} on_frames={frame_count} "
            f"on_vmstat={on_vmstat!r}"
        )
    return WallResult(
        cell=cell,
        off_s=off_s,
        on_s=on_s,
        context=tuple(context),
        on_frames=tuple(on_frames),
    )


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
        lines.append(f"- on_frames (FIX 1 guard, per trial): {list(r.on_frames)}")
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
            try:
                result = wall(cell, repeat=args.repeat, evidence_dir=args.out_dir)
            except TraceNotCapturedError as exc:
                # FIX 1: a cell whose trace-on leg traced nothing is aborted
                # LOUDLY and skipped, never folded into a PASS/FAIL/NOT
                # SEPARATED verdict it did not earn.
                print(f"  {cell}: ABORTED -- {exc}", file=sys.stderr)
                all_pass = False
                continue
            wall_results.append(result)
            verdict = wall_verdict(result)
            print(
                f"  {cell}: Rule W {verdict}  median_off={result.median_off:.3f}s "
                f"median_on={result.median_on:.3f}s ratio={result.ratio:.4f} "
                f"on_frames={list(result.on_frames)}",
                file=sys.stderr,
            )
            all_pass = all_pass and verdict == "PASS"
        out = args.out_dir / f"wall-{started.replace(':', '')}.md"
        out.write_text(_render_wall_markdown(wall_results))
        print(f"wall report -> {out}", file=sys.stderr)

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
