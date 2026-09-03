"""Can both strategies lay out everything, cleanly, right now?

    uv run python scripts/audit.py                    # every tier, powered
    uv run python scripts/audit.py --tier mid         # up to mid
    uv run python scripts/audit.py --budget 1,4,15    # sweep the solver budget
    uv run python scripts/audit.py --strategy sequence-pair
    uv run python scripts/audit.py --strategy all      # + the racing portfolio
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

*A wall-clock cap.* ``--max-seconds`` bounds the whole run and reports cells
whose atomic completion work continues after their requested search deadline.

Ordering matters for the pool: the stress tier goes first, because a 34s cell
picked up last leaves fifteen cores idle waiting for it.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.bench.corpus import URL_CORPUS, Tier  # noqa: E402
from flab2bp.cli import (  # noqa: E402
    add_candidate_policy_argument,
    candidate_policies_from_args,
)
from flab2bp.dsp import catalog  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.techs import belt_rules_for_url  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import finalize, route_kernel, validate  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import (  # noqa: E402
    ATOMIC_COMPLETION_GRACE_S,
    LayoutAttemptFailure,
    LayoutStrategy,
    NoValidLayout,
    PlacementCompletion,
    ProjectionFailureRecord,
)
from flab2bp.layout.freeform import FreeformLayout  # noqa: E402
from flab2bp.layout.sequence_solver import SequencePairLayout  # noqa: E402
from flab2bp.layout.strategy_race import (  # noqa: E402
    RACE_COMPLETION_GRACE_S,
    RacingLayout,
)
from flab2bp.rates import (  # noqa: E402
    DEFAULT_CANDIDATE_POLICIES,
    CandidatePolicy,
    build_candidates,
)
from flab2bp.spec import BuildSpec  # noqa: E402

_TIER_ORDER = (Tier.TRIVIAL, Tier.SMALL, Tier.MID, Tier.LARGE, Tier.STRESS)
#: The third argument is the CELL'S belt ceiling.  ``run_cell`` validates the
#: winner at ``belt_rules.max_z``, and a raced child that validates its own
#: incumbent at a DIFFERENT ceiling would publish a bound this cell then
#: rejects.  The two explicit lambdas ignore it -- neither layout takes a belt
#: ceiling, and only the racing child validates on its own.
_StrategyFactory = Callable[[int, bool, Fraction], LayoutStrategy]
_STRATEGIES: dict[str, _StrategyFactory] = {
    "freeform": lambda workers, vertical, _max_belt_z: FreeformLayout(
        band_policy=BandPolicy("portable"),
        workers=workers,
        belt_vertical_construction=vertical,
    ),
    "sequence-pair": lambda _workers, vertical, _max_belt_z: SequencePairLayout(
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=vertical,
    ),
    "best": lambda workers, vertical, max_belt_z: RacingLayout(
        BandPolicy("portable"),
        workers=workers,
        belt_vertical_construction=vertical,
        max_belt_z=max_belt_z,
    ),
}
_DEFAULT_STRATEGIES = ("freeform", "sequence-pair")
_ALL_STRATEGIES = ("freeform", "sequence-pair", "best")


def strategy_names(requested: str) -> tuple[str, ...]:
    """Resolve ``both`` to the two explicit strategies and ``all`` to all three."""
    if requested == "both":
        return _DEFAULT_STRATEGIES
    if requested == "all":
        return _ALL_STRATEGIES
    if requested not in _STRATEGIES:
        raise ValueError(f"unknown strategy: {requested}")
    return (requested,)


#: A cell slower than this is worth NAMING in the summary even when it passes.
#: This is a reporting threshold, not a defect threshold: see :func:`_slow_note`
#: for why a cell above it is usually behaving exactly as designed.
SLOW_CELL_S = 10.0


@dataclass(frozen=True)
class Job:
    """One audit cell. Plain data, because it crosses a process boundary."""

    strategy: str
    url_id: str
    url: str
    tier: str
    spec_index: int
    candidate_policies: tuple[CandidatePolicy, ...]
    budget: float
    workers: int
    #: Constant historical-schema metadata. Current audit cells are always powered.
    power: bool = field(init=False, default=True)
    #: Arrangements per height for freeform, or ``None`` for its own default.
    #: Only freeform has the notion, so it is passed only to freeform.
    arrangements: int | None = None

    @property
    def label(self) -> str:
        return f"{self.url_id}/#{self.spec_index} power={int(self.power)} budget={self.budget:g}s"


@dataclass(frozen=True)
class Result:
    """What a worker sends back. No Placement -- it does not need to travel."""

    job: Job
    status: str  # CLEAN | REFUSED | INVALID | CRASH | SPEC
    spec_label: str
    detail: str
    checks: tuple[str, ...]
    seconds: float
    #: Bounding-box tiles of the emitted placement; 0.0 when nothing was emitted.
    #:
    #: Density is the objective, so a change that buys clean cells by making the
    #: builds bigger has to be visible as such.  The tally alone cannot show it:
    #: an arm can go green on more cells and ship a worse blueprint on every one
    #: of them, which is exactly the trade a fallback makes.
    area: float = 0.0
    projection_frame_candidates: int = 0
    projection_count: int = 0
    projection_collider_pairs: int = 0
    projection_power_pairs: int = 0
    projection_sorters: int = 0
    attempt_failures: tuple[LayoutAttemptFailure, ...] = ()
    projection_failures: tuple[ProjectionFailureRecord, ...] = ()
    #: Routing kernel THIS WORKER PROCESS selected.  A property of the process,
    #: not of a placement, so it is present on REFUSED and CRASH rows too --
    #: which is the point: a refusal under the Python fallback is a different
    #: fact from a refusal under Cython, and a JSONL that cannot tell them apart
    #: cannot be compared against one taken with the other backend.
    route_backend: str = field(default_factory=route_kernel.selected_backend)
    #: Wall of the ATTEMPT -- the solve plus the compaction, projection and
    #: validation charged to nobody else -- and how far past ``budget + grace``
    #: it ran, clamped at zero, where ``grace`` is
    #: ``strategy_race.RACE_COMPLETION_GRACE_S`` for a ``best`` cell (a raced
    #: attempt runs under the race's own completion contract, not the serial
    #: one) and ``base.ATOMIC_COMPLETION_GRACE_S`` for every other strategy --
    #: the same two contracts ``pipeline`` honours on ``PlacementStats``.  The
    #: audit is its own driver, so it measures them itself rather than reading
    #: a stat no layout produces.
    #:
    #: ``None`` -- and therefore ABSENT from the JSONL row -- only when the
    #: cell produced no placement at all (a refusal before any layout was
    #: built).  A rejected placement still overshot something and carries both
    #: numbers; only a placement-free refusal overshot nothing, and a zero
    #: there would be indistinguishable from a punctual cell to whatever reports
    #: the maximum.
    attempt_wall_s: float | None = None
    wall_overshoot_s: float | None = None

    @property
    def label(self) -> str:
        return (
            f"{self.job.url_id}/{self.spec_label} power={int(self.job.power)} "
            f"budget={self.job.budget:g}s"
        )


# Per-process spec cache. Rebuilding candidates for every cell would re-run the
# rate solver six times per URL; a worker handles several cells of the same URL,
# so caching here pays for itself and cannot skew the layout timings.
_SPECS: dict[
    tuple[str, tuple[CandidatePolicy, ...]],
    tuple[BuildSpec, ...],
] = {}


def _specs_for(
    url: str,
    candidate_policies: tuple[
        CandidatePolicy, ...
    ] = DEFAULT_CANDIDATE_POLICIES,
) -> tuple[BuildSpec, ...]:
    key = (url, candidate_policies)
    if key not in _SPECS:
        _SPECS[key] = build_candidates(
            load_vendored(),
            parse_url(url),
            candidate_policies=candidate_policies,
        ).candidates
    return _SPECS[key]


def _belt_rules_for(url: str) -> catalog.BeltAltitudeRules:
    """The save's belt altitude rules, from this URL's researched technologies.

    THE AUDIT USED TO IGNORE THESE ENTIRELY, and it mattered twice over: it
    built both strategies with neither the slope rule nor the height ceiling,
    and it then validated the result without them too.  So every cell was
    measured against whatever the defaults happened to be rather than against
    the save the URL describes -- a corpus number that could not have caught a
    technology-dependent defect, in either direction.

    Delegates to :func:`flab2bp.lab.techs.belt_rules_for_url` so the audit and
    the production pipeline cannot drift apart on the question.
    """
    return belt_rules_for_url(url, load_vendored())


def run_cell(job: Job) -> Result:
    """Lay one cell out and judge it. Runs in a worker process."""
    t0 = time.monotonic()
    try:
        specs = _specs_for(job.url, job.candidate_policies)
    except Exception as exc:  # noqa: BLE001
        return Result(job, "SPEC", "?", f"{type(exc).__name__}: {exc}", (), time.monotonic() - t0)
    if job.spec_index >= len(specs):
        return Result(job, "SPEC", "?", "no such candidate", (), time.monotonic() - t0)
    spec = specs[job.spec_index]
    label = spec.label

    belt_rules = _belt_rules_for(job.url)
    make_strategy = _STRATEGIES[job.strategy]
    strategy: LayoutStrategy
    #: Everything from here on is the attempt: the search AND the completion,
    #: projection and validation that run after the strategy's own budget
    #: expires and are charged to nobody.  `t0` also covers building the spec,
    #: which is not the layout's cost.
    attempt_started = time.monotonic()
    #: A raced `best` cell runs under the race's own completion contract, not
    #: the serial one: `RacingLayout` gives its children until
    #: RACE_COMPLETION_GRACE_S (6.0) past the shared deadline, a full second
    #: more than the ATOMIC_COMPLETION_GRACE_S (5.0) a lone strategy gets.
    #: Judging every strategy by the serial grace would over-report a clean
    #: `best` cell's overshoot by up to that second.
    grace = RACE_COMPLETION_GRACE_S if job.strategy == "best" else ATOMIC_COMPLETION_GRACE_S
    try:
        if job.arrangements is not None and job.strategy == "freeform":
            strategy = FreeformLayout(
                band_policy=BandPolicy("portable"),
                workers=job.workers,
                arrangements=job.arrangements,
                belt_vertical_construction=belt_rules.vertical_construction,
            )
        else:
            strategy = make_strategy(
                job.workers,
                belt_rules.vertical_construction,
                belt_rules.max_z,
            )
        placement = strategy.lay_out(
            spec,
            time_budget_s=job.budget,
        )
    except NoValidLayout as exc:
        return Result(
            job,
            "REFUSED",
            label,
            exc.reason,
            ("<refused>",),
            time.monotonic() - t0,
            attempt_failures=exc.attempt_failures,
            projection_failures=exc.projection_failures,
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
    if placement.completion is not PlacementCompletion.COMPACTED_AND_FINALIZED:
        placement = finalize.compact_open_boundary_belts(
            placement,
            spec,
            expect_power=True,
        )
        try:
            placement = finalize.finalize_placement(placement, BandPolicy("portable"))
        except finalize.ProjectionRefusal as exc:
            reason = "final spherical projection rejected " + ", ".join(exc.checks)
            projection_failures = tuple(
                ProjectionFailureRecord(
                    band=failure.band,
                    check=failure.check,
                    buildings=failure.buildings,
                    detail=failure.detail,
                )
                for failure in exc.failures
            )
            # A placement WAS produced here -- it is what got projected and
            # rejected -- so the attempt spent its whole budget and the row is
            # honest carrying a wall and an overshoot, unlike the NoValidLayout
            # refusal above (which never had a placement to charge for).
            now = time.monotonic()
            attempt_wall_s = now - attempt_started
            wall_overshoot_s = max(0.0, attempt_wall_s - job.budget - grace)
            return Result(
                job,
                "REFUSED",
                label,
                reason[:70],
                exc.checks,
                now - t0,
                projection_failures=projection_failures,
                attempt_wall_s=attempt_wall_s,
                wall_overshoot_s=wall_overshoot_s,
            )
        placement = replace(
            placement,
            completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
        )
    projection_frame_candidates = int(placement.stats.get("projection_frame_candidates", 0))
    projection_count = int(placement.stats.get("projection_count", 0))
    projection_collider_pairs = int(placement.stats.get("projection_collider_pairs", 0))
    projection_power_pairs = int(placement.stats.get("projection_power_pairs", 0))
    projection_sorters = int(placement.stats.get("projection_sorters", 0))

    report = validate.validate(
        placement,
        spec,
        ids=validate.id_map(spec),
        expect_power=True,
        max_belt_z=belt_rules.max_z,
        belt_vertical_construction=belt_rules.vertical_construction,
    )
    now = time.monotonic()
    elapsed = now - t0
    attempt_wall_s = now - attempt_started
    wall_overshoot_s = max(
        0.0,
        attempt_wall_s - job.budget - grace,
    )
    skipped_power = tuple(c for c in report.skipped if c.startswith("power."))
    if report.ok and not skipped_power:
        return Result(
            job,
            "CLEAN",
            label,
            "",
            (),
            elapsed,
            float(placement.area),
            projection_frame_candidates,
            projection_count,
            projection_collider_pairs,
            projection_power_pairs,
            projection_sorters,
            attempt_wall_s=attempt_wall_s,
            wall_overshoot_s=wall_overshoot_s,
        )
    checks = tuple(sorted({f.check for f in report.errors})) + tuple(
        f"unchecked:{check}" for check in skipped_power
    )
    return Result(
        job,
        "INVALID",
        label,
        f"{len(report.errors)}e " + ",".join(checks)[:56],
        checks,
        elapsed,
        float(placement.area),
        projection_frame_candidates,
        projection_count,
        projection_collider_pairs,
        projection_power_pairs,
        projection_sorters,
        attempt_wall_s=attempt_wall_s,
        wall_overshoot_s=wall_overshoot_s,
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


def _deadline_note(count: int, max_tail_s: float) -> str:
    """Explain atomic completion work after each cell's own search deadline."""
    return (
        f"{count} cells completed after their own requested search deadline; "
        f"the largest completion tail was {max_tail_s:.1f}s. Emission, detailed "
        "routing already in flight, and validation finish atomically."
    )


def _record_number(record: dict[str, object], key: str) -> float:
    value = record[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"audit record {key!r} must be numeric")
    return float(value)


def _slugs(raw: str, flag: str) -> set[str]:
    """Parse a comma-separated ``url_id`` list, refusing ids the corpus lacks.

    A typo must not quietly select nothing.  An audit of zero cells finds zero
    faults, prints a clean tally and exits 0 -- the exact shape of a number that
    lies, and this project has been burned by one before.  So an unknown id is a
    hard error naming what is actually on offer.
    """
    known = {e.url_id for e in URL_CORPUS}
    want = {s.strip() for s in raw.split(",") if s.strip()}
    if not want:
        raise SystemExit(f"{flag}: empty; give at least one url_id")
    unknown = sorted(want - known)
    if unknown:
        raise SystemExit(
            f"{flag}: no such url_id: {', '.join(unknown)}\ncorpus has: {', '.join(sorted(known))}"
        )
    return want


def build_jobs(
    strategies: list[str],
    tiers: set[Tier],
    budgets: list[float],
    workers: int,
    candidate_policies: tuple[
        CandidatePolicy, ...
    ] = DEFAULT_CANDIDATE_POLICIES,
    only: set[str] | None = None,
    skip: set[str] | None = None,
    arrangements: int | None = None,
) -> list[Job]:
    """Every cell, hardest tier first so the pool does not end on a long tail."""
    entries = [e for e in URL_CORPUS if e.tier in tiers]
    if only:
        entries = [e for e in entries if e.url_id in only]
    if skip:
        entries = [e for e in entries if e.url_id not in skip]
    entries.sort(key=lambda e: _TIER_ORDER.index(e.tier), reverse=True)
    jobs = []
    for e in entries:
        for name in strategies:
            for i, _policy in enumerate(candidate_policies):
                for budget in budgets:
                    jobs.append(
                        Job(
                            strategy=name,
                            url_id=e.url_id,
                            url=e.url,
                            tier=e.tier.value,
                            spec_index=i,
                            candidate_policies=candidate_policies,
                            budget=budget,
                            workers=workers,
                            arrangements=arrangements,
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


def _head_commit() -> str:
    """The tree under audit, or ``"unknown"`` when git cannot say.

    An audit JSONL outlives the checkout that produced it.  Without this field a
    comparison of two files is a comparison of two anonymous runs, and the only
    way back to the code is the file's mtime.
    """
    try:
        finished = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10.0,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return finished.stdout.strip() or "unknown"


#: Stamped onto every row by ``record``.  Resolved once in ``main`` rather than
#: per cell: it is a property of the run, and 72 subprocess calls to learn one
#: constant is 72 chances to be slow or to disagree with itself.
_COMMIT = "unknown"


_JSONL: list[dict[str, object]] = []


def record(tallies: dict[str, Tally], r: Result) -> None:
    row: dict[str, object] = (
        {
            "strategy": r.job.strategy,
            "commit": _COMMIT,
            "route_backend": r.route_backend,
            "url_id": r.job.url_id,
            "spec_index": r.job.spec_index,
            "spec_label": r.spec_label,
            "power": r.job.power,
            "budget": r.job.budget,
            "status": r.status,
            "area": r.area,
            "seconds": r.seconds,
            "build_wall_time_s": r.seconds,
            "projection_frame_candidates": r.projection_frame_candidates,
            "projection_count": r.projection_count,
            "projection_collider_pairs": r.projection_collider_pairs,
            "projection_power_pairs": r.projection_power_pairs,
            "projection_sorters": r.projection_sorters,
            "attempt_failures": tuple(
                asdict(failure) for failure in r.attempt_failures
            ),
            "projection_failures": tuple(
                asdict(failure) for failure in r.projection_failures
            ),
            "detail": r.detail,
        }
    )
    # Present exactly where a placement was measured.  A reader takes them with
    # `row.get`: a REFUSED or CRASH row never had a placement, so it carries no
    # wall to compare and no overshoot to report.
    if r.attempt_wall_s is not None:
        row["attempt_wall_s"] = r.attempt_wall_s
    if r.wall_overshoot_s is not None:
        row["wall_overshoot_s"] = r.wall_overshoot_s
    _JSONL.append(row)
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


def build_parser() -> argparse.ArgumentParser:
    """Every flag this audit accepts, in one place a test can parse without main.

    Extracted from :func:`main` so a flag's exact surface -- ``--strategy``'s
    choices among them -- can be asserted on directly rather than only through
    the functions those choices are later handed to.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", default="stress", choices=[t.value for t in _TIER_ORDER])
    ap.add_argument(
        "--budget",
        default="15",
        help="comma-separated solver budgets in seconds; sweeping is the point",
    )
    add_candidate_policy_argument(ap)
    ap.add_argument(
        "--strategy",
        default="both",
        choices=("both", "all", "freeform", "sequence-pair", "best"),
        help="which arms to audit; both = the two explicit strategies (72 "
        "cells), all = those plus the racing portfolio (108 cells)",
    )
    ap.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="cells in parallel (0 = cores//16). Sequence cells run two complete "
        "islands, so the default reserves sixteen cores per cell.",
    )
    ap.add_argument(
        "--max-seconds",
        type=float,
        default=900.0,
        help="hard cap on the whole run; unreached cells report NOT RUN and the "
        "gate fails, because a truncated audit is not a clean one",
    )
    ap.add_argument(
        "--only",
        default="",
        help="comma-separated url_ids to audit, e.g. universe-matrix,quantum-chip. "
        "A six-cell question should not cost a seventy-two-cell run; an unknown "
        "id is an error rather than an empty, vacuously clean audit.",
    )
    ap.add_argument(
        "--skip",
        default="",
        help="comma-separated url_ids to leave out, applied after --only",
    )
    ap.add_argument(
        "--arrangements",
        type=int,
        default=None,
        help="freeform only: arrangements per candidate height. Omit for the "
        "measured default; 1 is the search as it stood before arrangements "
        "existed, which is what an A/B compares against",
    )
    ap.add_argument("--quiet", action="store_true", help="totals only, no per-cell miss list")
    ap.add_argument(
        "--json",
        default="",
        help="append one JSON record per cell to this file, so two arms can be "
        "compared cell-by-cell and on area rather than on a tally that hides "
        "which cells moved and what they cost",
    )
    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    global _COMMIT
    _COMMIT = _head_commit()
    candidate_policies = candidate_policies_from_args(ap, args)

    cutoff = _TIER_ORDER.index(Tier(args.tier))
    tiers = set(_TIER_ORDER[: cutoff + 1])
    budgets = [float(b) for b in args.budget.split(",")]
    names = list(strategy_names(args.strategy))

    cores = _available_cores()
    jobs_n = args.jobs if args.jobs > 0 else max(1, cores // 16)
    per_cell_workers = max(1, cores // jobs_n)
    only = _slugs(args.only, "--only") if args.only else None
    skip = _slugs(args.skip, "--skip") if args.skip else None
    jobs = build_jobs(
        names,
        tiers,
        budgets,
        per_cell_workers,
        candidate_policies=candidate_policies,
        only=only,
        skip=skip,
        arrangements=args.arrangements,
    )
    if not jobs:
        raise SystemExit(
            "no cells selected: --only and --skip between them left nothing to "
            "audit, and an audit of nothing is not a clean audit"
        )

    selected = "" if only is None and skip is None else f" of {args.tier}"
    print(
        f"{len(jobs)} cells{selected}, {jobs_n} at a time, {per_cell_workers} CP-SAT "
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
    if args.json:
        import json as _json

        with open(args.json, "a", encoding="utf-8") as fh:
            for rec in _JSONL:
                fh.write(_json.dumps(rec) + "\n")
    print(f"\n{elapsed:.0f}s wall, {done}/{len(jobs)} cells")
    deadline_tails = [
        _record_number(record, "seconds") - _record_number(record, "budget")
        for record in _JSONL
        if _record_number(record, "seconds") > _record_number(record, "budget")
    ]
    if deadline_tails:
        print(_deadline_note(len(deadline_tails), max(deadline_tails)))
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
