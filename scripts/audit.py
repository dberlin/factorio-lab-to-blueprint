"""Can both strategies lay out everything, cleanly, right now?

    uv run python scripts/audit.py                    # every tier, both power settings
    uv run python scripts/audit.py --tier mid         # up to mid
    uv run python scripts/audit.py --budget 1,4,15    # sweep the solver budget
    uv run python scripts/audit.py --strategy spine
    uv run python scripts/audit.py --jobs 1           # serial, for honest timing

Exits non-zero if any cell is not clean, so it works as a gate.

WHY THIS IS A SCRIPT AND NOT A TEST
-----------------------------------
The whole matrix is minutes of CP-SAT and the test suite is deliberately ~24s.
Putting this in ``pytest`` would either make the suite unusable in an edit loop
or force it down to a sample so small it stops being the guarantee it exists to
be.  It is the gate you run before believing "both strategies work".

WHAT COUNTS AS A FAILURE, AND WHY THE DISTINCTION MATTERS
--------------------------------------------------------
Four ways a cell can miss, and they call for opposite fixes:

* ``REFUSED`` -- the strategy searched and raised ``NoValidLayout``.  Honest, and
  the *better* failure: nothing broken is emitted.
* ``INVALID`` -- it produced a placement the validator rejected.  Worse than
  refusing, because a blueprint that pastes and then does not run is the one
  outcome nobody discovers until they are standing in front of it in game.
* ``CRASH`` -- an unexpected exception.  Always a bug here, never the spec's
  fault.
* ``NOT RUN`` -- the wall-clock cap expired first.  Not a verdict on the cell;
  a verdict on this run.  Counted as a failure so a truncated audit can never
  be mistaken for a clean one.

A budget sweep is not optional padding.  CP-SAT is time-limited and multi-worker
by default, so a spec that validates at 4s may not at 1s, and "clean" that only
holds at one budget is not clean.  A LOW budget producing INVALID rather than
REFUSED is a serious finding: it means the feasibility check is budget-dependent
somewhere it should not be.

WHY THIS RUNS IN PARALLEL, AND WHY IT PRINTS AS IT GOES
------------------------------------------------------
Serial, silent and slow is what made this unusable: a full sweep took 100
minutes with no output, which is indistinguishable from a hang, and it was
killed twice before finishing.  Three things fix that, and all three are needed.

*Parallelism.*  Cells are completely independent, so they fan out over
processes.  The catch is that ``DEFAULT_SEARCH_WORKERS = 0`` means each solve
already takes every core, so ``--jobs N`` also pins each cell to ``cores // N``
search workers.  Total CP-SAT threads stay near the core count instead of N
times it -- oversubscribed solvers are slower per cell AND wronger, since a
time-limited solver starved of threads explores less in its allotted seconds.

*Progress.*  Every cell prints when it lands, slowest-first, so a long run is
visibly working rather than apparently wedged.

*A wall-clock cap.*  ``--max-seconds`` bounds the whole run.  What it exists to
catch is a strategy overrunning its own ``time_budget_s`` -- which is not
hypothetical: at ``--budget 4`` a freeform ``quantum-chip`` cell measured 80s,
and a spine ``universe-matrix`` cell 23s, because the budget bounded packing
while routing, escalation and last-resort passes each spent their own.  The cap
turns that from a 100-minute mystery into a named finding.

Ordering matters for the pool: the stress tier goes first, because a 34s cell
picked up last leaves fifteen cores idle waiting for it.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.bench.corpus import URL_CORPUS, Tier  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import validate  # noqa: E402
from flab2bp.layout.base import LayoutStrategy, NoValidLayout  # noqa: E402
from flab2bp.layout.freeform import FreeformLayout  # noqa: E402
from flab2bp.layout.spine import SpineLayout  # noqa: E402
from flab2bp.rates.candidates import build_candidates  # noqa: E402

_TIER_ORDER = (Tier.TRIVIAL, Tier.SMALL, Tier.MID, Tier.LARGE, Tier.STRESS)
_STRATEGIES: dict[str, type[LayoutStrategy]] = {
    "spine": SpineLayout,
    "freeform": FreeformLayout,
}

#: A cell slower than this is worth naming in the summary even when it passes.
#: Budgets in this corpus are single-digit seconds, so anything here is a cell
#: outrunning what it was given.
SLOW_CELL_S = 10.0


@dataclass(frozen=True)
class Job:
    """One audit cell. Plain data, because it crosses a process boundary."""

    strategy: str
    url_id: str
    url: str
    tier: str
    spec_index: int
    candidates: int
    budget: float
    power: bool
    workers: int

    @property
    def label(self) -> str:
        return (
            f"{self.url_id}/#{self.spec_index} power={int(self.power)} "
            f"budget={self.budget:g}s"
        )


@dataclass(frozen=True)
class Result:
    """What a worker sends back. No Placement -- it does not need to travel."""

    job: Job
    status: str  # CLEAN | REFUSED | INVALID | CRASH | SPEC
    spec_label: str
    detail: str
    checks: tuple[str, ...]
    seconds: float

    @property
    def label(self) -> str:
        return (
            f"{self.job.url_id}/{self.spec_label} power={int(self.job.power)} "
            f"budget={self.job.budget:g}s"
        )


# Per-process spec cache. Rebuilding candidates for every cell would re-run the
# rate solver six times per URL; a worker handles several cells of the same URL,
# so caching here pays for itself and cannot skew the layout timings.
_SPECS: dict[tuple[str, int], tuple[object, ...]] = {}


def _specs_for(url: str, count: int) -> tuple[object, ...]:
    key = (url, count)
    if key not in _SPECS:
        _SPECS[key] = build_candidates(
            load_vendored(), parse_url(url), count=count
        ).candidates
    return _SPECS[key]


def run_cell(job: Job) -> Result:
    """Lay one cell out and judge it. Runs in a worker process."""
    t0 = time.monotonic()
    try:
        specs = _specs_for(job.url, job.candidates)
    except Exception as exc:  # noqa: BLE001
        return Result(
            job, "SPEC", "?", f"{type(exc).__name__}: {exc}", (), time.monotonic() - t0
        )
    if job.spec_index >= len(specs):
        return Result(job, "SPEC", "?", "no such candidate", (), time.monotonic() - t0)
    spec = specs[job.spec_index]
    label = spec.label  # type: ignore[attr-defined]

    cls = _STRATEGIES[job.strategy]
    try:
        placement = cls(power=job.power, workers=job.workers).lay_out(  # type: ignore[call-arg]
            spec,  # type: ignore[arg-type]
            time_budget_s=job.budget,
        )
    except NoValidLayout as exc:
        return Result(
            job, "REFUSED", label, exc.reason[:70], ("<refused>",), time.monotonic() - t0
        )
    except Exception as exc:  # noqa: BLE001
        return Result(
            job,
            "CRASH",
            label,
            f"{type(exc).__name__}: {str(exc)[:56]}",
            ("<crash>",),
            time.monotonic() - t0,
        )

    report = validate.validate(
        placement,
        spec,  # type: ignore[arg-type]
        ids=validate.id_map(spec),  # type: ignore[arg-type]
        expect_power=job.power,
    )
    elapsed = time.monotonic() - t0
    if report.ok:
        return Result(job, "CLEAN", label, "", (), elapsed)
    checks = tuple(sorted({f.check for f in report.errors}))
    return Result(
        job, "INVALID", label, f"{len(report.errors)}e " + ",".join(checks)[:56], checks, elapsed
    )


@dataclass
class Tally:
    clean: int = 0
    refused: int = 0
    invalid: int = 0
    crashed: int = 0
    not_run: int = 0
    checks: Counter[str] = field(default_factory=Counter)
    misses: list[str] = field(default_factory=list)
    slowest: list[tuple[float, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.clean + self.refused + self.invalid + self.crashed + self.not_run


def build_jobs(
    strategies: list[str],
    tiers: set[Tier],
    budgets: list[float],
    candidates: int,
    workers: int,
) -> list[Job]:
    """Every cell, hardest tier first so the pool does not end on a long tail."""
    entries = [e for e in URL_CORPUS if e.tier in tiers]
    entries.sort(key=lambda e: _TIER_ORDER.index(e.tier), reverse=True)
    jobs = []
    for e in entries:
        for name in strategies:
            for i in range(candidates):
                for budget in budgets:
                    for power in (False, True):
                        jobs.append(
                            Job(
                                strategy=name,
                                url_id=e.url_id,
                                url=e.url,
                                tier=e.tier.value,
                                spec_index=i,
                                candidates=candidates,
                                budget=budget,
                                power=power,
                                workers=workers,
                            )
                        )
    return jobs


def _available_cores() -> int:
    """Cores this process may actually run on, not cores the box has.

    ``os.cpu_count()`` reports the machine.  Under ``taskset`` -- which is how
    two agents share one box without lying to each other about their budgets --
    that overstates the truth by however much of the machine was withheld, and
    every ``cores // jobs`` below it inherits the error as oversubscription.
    """
    affinity = getattr(os, "sched_getaffinity", None)  # Linux only.
    if affinity is not None:
        return len(affinity(0)) or 4
    return os.cpu_count() or 4


def record(tallies: dict[str, Tally], r: Result) -> None:
    t = tallies[r.job.strategy]
    t.slowest.append((r.seconds, f"{r.job.strategy} {r.label}"))
    if r.status == "CLEAN":
        t.clean += 1
        return
    if r.status == "REFUSED":
        t.refused += 1
    elif r.status == "INVALID":
        t.invalid += 1
    elif r.status == "CRASH":
        t.crashed += 1
    else:  # SPEC failure is not the layout's fault, but it is still not clean.
        t.crashed += 1
    for c in r.checks:
        t.checks[c] += 1
    t.misses.append(f"{r.status:<8} {r.label}  {r.detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", default="stress", choices=[t.value for t in _TIER_ORDER])
    ap.add_argument(
        "--budget",
        default="4",
        help="comma-separated solver budgets in seconds; sweeping is the point",
    )
    ap.add_argument("--candidates", type=int, default=3)
    ap.add_argument("--strategy", default="both", choices=("both", "spine", "freeform"))
    ap.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="cells in parallel (0 = cores//4). Each cell is pinned to "
        "cores//jobs CP-SAT workers so the machine is not oversubscribed.",
    )
    ap.add_argument(
        "--max-seconds",
        type=float,
        default=900.0,
        help="hard cap on the whole run; unreached cells report NOT RUN and the "
        "gate fails, because a truncated audit is not a clean one",
    )
    ap.add_argument(
        "--quiet", action="store_true", help="totals only, no per-cell miss list"
    )
    args = ap.parse_args()

    cutoff = _TIER_ORDER.index(Tier(args.tier))
    tiers = set(_TIER_ORDER[: cutoff + 1])
    budgets = [float(b) for b in args.budget.split(",")]
    names = list(_STRATEGIES) if args.strategy == "both" else [args.strategy]

    cores = _available_cores()
    jobs_n = args.jobs if args.jobs > 0 else max(1, cores // 4)
    per_cell_workers = max(1, cores // jobs_n)
    jobs = build_jobs(names, tiers, budgets, args.candidates, per_cell_workers)

    print(
        f"{len(jobs)} cells, {jobs_n} at a time, {per_cell_workers} CP-SAT "
        f"workers each, cap {args.max_seconds:g}s",
        flush=True,
    )

    tallies = {name: Tally() for name in names}
    t0 = time.monotonic()
    done = 0
    expired = False

    if jobs_n == 1:
        for job in jobs:
            if time.monotonic() - t0 > args.max_seconds:
                expired = True
                break
            r = run_cell(job)
            done += 1
            record(tallies, r)
            _echo(r, done, len(jobs), time.monotonic() - t0)
        remaining = len(jobs) - done
    else:
        with ProcessPoolExecutor(max_workers=jobs_n) as pool:
            futures = {pool.submit(run_cell, j): j for j in jobs}
            pending = set(futures)
            while pending:
                left = args.max_seconds - (time.monotonic() - t0)
                if left <= 0:
                    expired = True
                    break
                finished, pending = wait(pending, timeout=left, return_when=FIRST_COMPLETED)
                for fut in finished:
                    r = fut.result()
                    done += 1
                    record(tallies, r)
                    _echo(r, done, len(jobs), time.monotonic() - t0)
            for fut in pending:
                fut.cancel()
            remaining = len(pending)
        if expired and remaining:
            # Cancelling does not stop a cell already running, so the pool's
            # shutdown may have let a few more land. Trust `done`.
            remaining = len(jobs) - done

    if expired:
        # Charge the unreached cells to whichever strategies were being audited.
        # Spreading them evenly would be a guess; naming the count is not.
        for name in names:
            share = sum(1 for j in jobs[done:] if j.strategy == name)
            tallies[name].not_run += share
        print(
            f"\n!! WALL-CLOCK CAP HIT at {args.max_seconds:g}s with "
            f"{len(jobs) - done} cells unreached.",
            flush=True,
        )

    failed = False
    for name, t in tallies.items():
        status = "CLEAN" if t.clean == t.total else "NOT CLEAN"
        print(
            f"\n=== {name}: {t.clean}/{t.total} clean -- {status}"
            f"   (refused {t.refused}, invalid {t.invalid}, crashed {t.crashed}"
            f", not run {t.not_run})"
        )
        if t.clean != t.total:
            failed = True
            print(f"    by check: {dict(t.checks.most_common())}")
            if not args.quiet:
                for m in t.misses:
                    print(f"    {m}")
        slow = sorted((s for s in t.slowest if s[0] >= SLOW_CELL_S), reverse=True)[:5]
        if slow:
            print("    slowest: " + ", ".join(f"{s:.0f}s {lbl}" for s, lbl in slow))

    elapsed = time.monotonic() - t0
    print(f"\n{elapsed:.0f}s wall, {done}/{len(jobs)} cells")
    over = [s for t in tallies.values() for s in t.slowest if s[0] >= SLOW_CELL_S]
    if over:
        print(
            f"{len(over)} cells took {SLOW_CELL_S:g}s or more. Budgets here are "
            "single-digit seconds, so those cells are outrunning what they were "
            "given -- a lay_out that does not honour time_budget_s, not a slow "
            "machine."
        )
    if failed:
        print(
            "\nNOT CLEAN. An INVALID cell is worse than a REFUSED one: refusing "
            "emits nothing, while an invalid blueprint pastes and then does not "
            "run. Fix the invalid ones first."
        )
    return 1 if failed else 0


def _echo(r: Result, done: int, total: int, elapsed: float) -> None:
    mark = "." if r.status == "CLEAN" else "X"
    slow = f"  <-- {r.seconds:.0f}s" if r.seconds >= SLOW_CELL_S else ""
    print(
        f"  {mark} [{done:>3}/{total}] {elapsed:5.0f}s {r.job.strategy:<9} "
        f"{r.job.tier:<8} {r.label:<52} {r.status:<8} {r.seconds:5.1f}s{slow}",
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
