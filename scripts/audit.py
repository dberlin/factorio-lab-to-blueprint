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
import multiprocessing as mp
import os
import signal
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, MutableSequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from multiprocessing.synchronize import Lock
from pathlib import Path
from time import perf_counter
from typing import cast

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
from flab2bp.layout.coater_mode import coater_mode  # noqa: E402
from flab2bp.layout.freeform import FreeformLayout  # noqa: E402
from flab2bp.layout.sequence_solver import SequencePairLayout  # noqa: E402
from flab2bp.layout.strategy_race import (  # noqa: E402
    RACE_COMPLETION_GRACE_S,
    RacingLayout,
)
from flab2bp.pipeline import _resolve_power_tower, resolve_sequence_islands  # noqa: E402
from flab2bp.rates import (  # noqa: E402
    DEFAULT_CANDIDATE_POLICIES,
    CandidatePolicy,
    build_candidates,
)
from flab2bp.rates.machine_choice import MachineRank  # noqa: E402
from flab2bp.spec import BuildSpec  # noqa: E402

_TIER_ORDER = (Tier.TRIVIAL, Tier.SMALL, Tier.MID, Tier.LARGE, Tier.STRESS)
#: The same complete policy reaches construction and final judgment.
_StrategyFactory = Callable[[int, catalog.BeltAltitudeRules], LayoutStrategy]
_STRATEGIES: dict[str, _StrategyFactory] = {
    "freeform": lambda workers, rules: FreeformLayout(
        band_policy=BandPolicy("portable"),
        workers=workers,
        belt_vertical_construction=rules.vertical_construction,
    ),
    #: Islands, at the same count production runs, so the gate MEASURES the
    #: default rather than a shape no user gets.  `resolve_sequence_islands`
    #: bounds them by this cell's own CP-SAT worker share, so a wide `--jobs`
    #: run -- which gives each cell fewer workers -- narrows the islands with it
    #: instead of oversubscribing the box N times over.
    "sequence-pair": lambda workers, rules: SequencePairLayout(
        band_policy=BandPolicy("portable"),
        belt_vertical_construction=rules.vertical_construction,
        islands=resolve_sequence_islands("sequence-pair", workers, None),
    ),
    "best": lambda workers, rules: RacingLayout(
        BandPolicy("portable"),
        workers=workers,
        belt_vertical_construction=rules.vertical_construction,
        sequence_islands=resolve_sequence_islands("best", workers, None),
        max_belt_z=rules.max_z,
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
    machine_rank: str = MachineRank.EXACT.value
    #: Constant historical-schema metadata. Current audit cells are always powered.
    power: bool = field(init=False, default=True)
    #: Arrangements per height for freeform, or ``None`` for its own default.
    #: Only freeform has the notion, so it is passed only to freeform.
    arrangements: int | None = None
    power_tower: str | None = None

    @property
    def label(self) -> str:
        return f"{self.url_id}/#{self.spec_index} power={int(self.power)} budget={self.budget:g}s"


@dataclass(frozen=True)
class Result:
    """A job-owned terminal outcome; no Placement needs to travel to the supervisor."""

    job: Job
    status: str  # CLEAN | REFUSED | INVALID | CRASH | SPEC | TERMINATED | NOT_RUN
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
    #: ``FLAB2BP_COATER_NODE`` arm census: coaters placed, coater bodies
    #: sitting over a belt with two predecessors, and belt tiles.  Zero on a
    #: row with no placement.
    coaters: int = 0
    coater_merges: int = 0
    belt_tiles: int = 0
    power_towers: int = 0
    #: Wall of the ATTEMPT -- the solve plus the compaction, projection and
    #: validation charged to nobody else -- and how far past ``budget + grace``
    #: it ran, clamped at zero, where ``grace`` is
    #: ``strategy_race.RACE_COMPLETION_GRACE_S`` for any cell that runs a child
    #: pool -- ``best``, and ``sequence-pair`` once its islands resolve above
    #: one, since the island runner now takes that same grace -- (a raced
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
    #: Solver telemetry for THIS cell.  Present on CLEAN rows from
    #: `PlacementStats` and on REFUSED rows from `NoValidLayout.stats` or the
    #: rejected placement's own stats; absent from the JSONL when empty, and read
    #: as empty by every consumer.  Values are numbers except `alns_operators`,
    #: which is a tally string.
    stats: dict[str, float | str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.spec_label == "?":
            return self.job.label
        return (
            f"{self.job.url_id}/{self.spec_label} power={int(self.job.power)} "
            f"budget={self.job.budget:g}s"
        )


def _scalar_stats(mapping: Mapping[str, object]) -> dict[str, float | str]:
    """Narrow a stats mapping to what `Result.stats` can actually hold.

    `PlacementStats` also carries non-scalar keys -- `archive_categories` and
    `belt_upgrade_tiers` are `list[str]` -- that a `dict(...)` copy would pass
    straight through into a `dict[str, float | str]`-typed field with nothing
    to catch it at runtime.  This is the one place that boundary is drawn:
    every ``int``/``float`` becomes a ``float``, every ``str`` is kept as is,
    and everything else (lists included) is dropped.  ``bool`` is excluded
    deliberately even though it is an ``int`` subclass; `PlacementStats`
    declares none today, and a stray one silently becoming ``0.0``/``1.0``
    would be a worse surprise than dropping it.
    """
    scalars: dict[str, float | str] = {}
    for key, value in mapping.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            scalars[key] = float(value)
        elif isinstance(value, str):
            scalars[key] = value
    return scalars


# Per-process spec cache. Rebuilding candidates for every cell would re-run the
# rate solver six times per URL; a worker handles several cells of the same URL,
# so caching here pays for itself and cannot skew the layout timings.
_SPECS: dict[
    tuple[str, tuple[CandidatePolicy, ...], MachineRank, str | None],
    tuple[BuildSpec, ...],
] = {}


def _specs_for(
    url: str,
    candidate_policies: tuple[CandidatePolicy, ...] = DEFAULT_CANDIDATE_POLICIES,
    machine_rank: MachineRank = MachineRank.EXACT,
    power_tower: str | None = None,
) -> tuple[BuildSpec, ...]:
    key = (url, candidate_policies, machine_rank, power_tower)
    if key not in _SPECS:
        request = parse_url(url)
        _SPECS[key] = build_candidates(
            load_vendored(),
            request,
            candidate_policies=candidate_policies,
            machine_rank=machine_rank,
            power_tower_item_id=_resolve_power_tower(power_tower, request),
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


def run_cell(job: Job, *, belt_rules: catalog.BeltAltitudeRules) -> Result:
    """Lay one cell out and judge it. Runs in a worker process."""
    t0 = time.monotonic()
    try:
        specs = _specs_for(
            job.url,
            job.candidate_policies,
            machine_rank=MachineRank(job.machine_rank),
            power_tower=job.power_tower,
        )
    except Exception as exc:  # noqa: BLE001
        return Result(job, "SPEC", "?", f"{type(exc).__name__}: {exc}", (), time.monotonic() - t0)
    if job.spec_index >= len(specs):
        return Result(job, "SPEC", "?", "no such candidate", (), time.monotonic() - t0)
    spec = specs[job.spec_index]
    label = spec.label

    make_strategy = _STRATEGIES[job.strategy]
    strategy: LayoutStrategy
    #: Everything from here on is the attempt: the search AND the completion,
    #: projection and validation that run after the strategy's own budget
    #: expires and are charged to nobody.  `t0` also covers building the spec,
    #: which is not the layout's cost.
    attempt_started = time.monotonic()
    #: A cell that runs a CHILD POOL runs under the pool's completion contract,
    #: not the serial one: both `RacingLayout` and the island runner give their
    #: children until RACE_COMPLETION_GRACE_S (6.0) past the shared deadline, a
    #: full second more than the ATOMIC_COMPLETION_GRACE_S (5.0) a lone
    #: in-process strategy gets.  Judging those by the serial grace would
    #: over-report a clean cell's overshoot by up to that second.  A
    #: `sequence-pair` cell resolved to one island has no pool and stays atomic.
    grace = (
        RACE_COMPLETION_GRACE_S
        if job.strategy == "best"
        or (
            job.strategy == "sequence-pair"
            and resolve_sequence_islands("sequence-pair", job.workers, None) > 1
        )
        else ATOMIC_COMPLETION_GRACE_S
    )
    try:
        if job.arrangements is not None and job.strategy == "freeform":
            strategy = FreeformLayout(
                band_policy=BandPolicy("portable"),
                workers=job.workers,
                arrangements=job.arrangements,
                belt_vertical_construction=belt_rules.vertical_construction,
            )
        else:
            strategy = make_strategy(job.workers, belt_rules)
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
            stats=_scalar_stats(exc.stats),
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
                stats=_scalar_stats(placement.stats),
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

    report = validate.judge_placement(
        placement,
        spec,
        ids=validate.id_map(spec),
        expect_power=True,
        belt_rules=belt_rules,
    )
    now = time.monotonic()
    elapsed = now - t0
    attempt_wall_s = now - attempt_started
    wall_overshoot_s = max(
        0.0,
        attempt_wall_s - job.budget - grace,
    )
    coaters, coater_merges, belt_tiles = _coater_census(placement)
    power_towers = sum(
        catalog.building(building.item_id).is_power_node for building in placement.buildings
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
            stats=_scalar_stats(placement.stats),
            coaters=coaters,
            coater_merges=coater_merges,
            belt_tiles=belt_tiles,
            power_towers=power_towers,
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
        stats=_scalar_stats(placement.stats),
        coaters=coaters,
        coater_merges=coater_merges,
        belt_tiles=belt_tiles,
        power_towers=power_towers,
    )


def _coater_census(placement: object) -> tuple[int, int, int]:
    """``(coaters, bodies over a belt merge, belt tiles)`` for one placement.

    ``FLAB2BP_COATER_NODE``.  The middle number is the reported
    defect measured directly rather than inferred: a Spray Coater's oriented
    3x1 body covers three tiles, and a belt on one of them with more than one
    predecessor is a 2-into-1 merge under the addon.  ``layout/validate.py``'s
    ``prolif.coater_rides_one_run`` now convicts exactly this -- but this
    census still counts it directly, rather than inferring it from that
    check's findings, so an arm comparison run against a placement that never
    reached the validator (or against an older build predating that check)
    still sees the thing the arms exist to remove.
    """
    from collections import defaultdict as _dd

    bs = placement.buildings  # type: ignore[attr-defined]
    belts = {(b.x, b.y, b.z): i for i, b in enumerate(bs) if catalog.is_belt(b.item_id)}
    pred: dict[int, int] = _dd(int)
    for b in bs:
        if not catalog.is_belt(b.item_id):
            continue
        if b.output_obj is not None and 0 <= b.output_obj < len(bs):
            pred[b.output_obj] += 1
    merges = 0
    coaters = 0
    for c in bs:
        if c.item_id != catalog.SPRAY_COATER_ID:
            continue
        coaters += 1
        half = (catalog.oriented_footprint(catalog.SPRAY_COATER_ID, c.yaw)[0] - 1) // 2
        for dx in range(-half, half + 1):
            belt = belts.get((c.x + dx, c.y, c.z))
            if belt is not None and pred[belt] > 1:
                merges += 1
    return coaters, merges, len(belts)


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
    candidate_policies: tuple[CandidatePolicy, ...] = DEFAULT_CANDIDATE_POLICIES,
    only: set[str] | None = None,
    skip: set[str] | None = None,
    arrangements: int | None = None,
    machine_rank: str = MachineRank.EXACT.value,
    power_tower: str | None = None,
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
                            machine_rank=machine_rank,
                            arrangements=arrangements,
                            power_tower=power_tower,
                        )
                    )
    if len(set(jobs)) != len(jobs):
        raise ValueError("duplicate selected audit job")
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


def _head_commit(*, timeout_s: float = 10.0) -> str:
    """The tree under audit, or ``"unknown"`` when git cannot say.

    An audit JSONL outlives the checkout that produced it.  Without this field a
    comparison of two files is a comparison of two anonymous runs, and the only
    way back to the code is the file's mtime.
    """
    if timeout_s <= 0:
        return "unknown"
    try:
        finished = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=min(10.0, timeout_s),
        )
    except OSError, subprocess.SubprocessError:
        return "unknown"
    return finished.stdout.strip() or "unknown"


#: Stamped onto every row by ``record``.  Resolved once in ``main`` rather than
#: per cell: it is a property of the run, and 72 subprocess calls to learn one
#: constant is 72 chances to be slow or to disagree with itself.
_COMMIT = "unknown"


_JSONL: list[dict[str, object]] = []


def record(tallies: dict[str, Tally], r: Result) -> None:
    row: dict[str, object] = {
        "strategy": r.job.strategy,
        "commit": _COMMIT,
        "route_backend": r.route_backend,
        "url_id": r.job.url_id,
        "spec_index": r.job.spec_index,
        "spec_label": r.spec_label,
        "power": r.job.power,
        "power_tower": r.job.power_tower or "auto",
        "power_towers": r.power_towers,
        "budget": r.job.budget,
        "machine_rank": r.job.machine_rank,
        "arrangements": r.job.arrangements,
        "status": r.status,
        "area": r.area,
        "seconds": r.seconds,
        "build_wall_time_s": r.seconds,
        "projection_frame_candidates": r.projection_frame_candidates,
        "projection_count": r.projection_count,
        "projection_collider_pairs": r.projection_collider_pairs,
        "projection_power_pairs": r.projection_power_pairs,
        "projection_sorters": r.projection_sorters,
        "coater_arm": coater_mode().value,
        "coaters": r.coaters,
        "coater_merges": r.coater_merges,
        "belt_tiles": r.belt_tiles,
        "attempt_failures": tuple(asdict(failure) for failure in r.attempt_failures),
        "projection_failures": tuple(asdict(failure) for failure in r.projection_failures),
        "detail": r.detail,
    }
    # Present exactly where a placement was measured.  A reader takes them with
    # `row.get`: a REFUSED or CRASH row never had a placement, so it carries no
    # wall to compare and no overshoot to report.
    if r.attempt_wall_s is not None:
        row["attempt_wall_s"] = r.attempt_wall_s
    if r.wall_overshoot_s is not None:
        row["wall_overshoot_s"] = r.wall_overshoot_s
    # Present exactly where the strategy produced numbers.  A CRASH or SPEC row
    # never reached a solver, so it carries none and the key is absent.
    if r.stats:
        row["stats"] = dict(r.stats)
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
    elif r.status in {"TERMINATED", "NOT_RUN"}:
        t.not_run += 1
    else:  # SPEC failure is not the layout's fault, but it is still not clean.
        t.crashed += 1
    for c in r.checks:
        t.checks[c] += 1
    t.misses.append(f"{r.status:<8} {r.label}  {r.detail}")


_JOB_STARTED: MutableSequence[int] | None = None


def _initialize_audit_worker(
    groups: MutableSequence[int], lock: Lock, started: MutableSequence[int]
) -> None:
    """Own a session before any preparation or nested layout work can start."""
    global _JOB_STARTED
    os.setsid()
    with lock:
        groups[next(index for index, pid in enumerate(groups) if pid == 0)] = os.getpid()
    _JOB_STARTED = started


def _run_started_cell(job_id: int, job: Job, belt_rules: catalog.BeltAltitudeRules) -> Result:
    assert _JOB_STARTED is not None
    _JOB_STARTED[job_id] = 1
    return run_cell(job, belt_rules=belt_rules)


def _stop_audit_workers(
    pool: ProcessPoolExecutor, groups: MutableSequence[int], prior_children: frozenset[int]
) -> None:
    """Stop owned sessions, then release the executor's interrupted result reader."""
    # Python 3.14 force shutdown discards these handles before its manager exits.
    # Retain the owners just as the production race teardown does.
    manager = getattr(pool, "_executor_manager_thread", None)
    result_queue = getattr(pool, "_result_queue", None)
    children = [child for child in mp.active_children() if child.pid not in prior_children]
    # Each registered group was created by our initializer, never guessed from
    # a process listing. Nested spawn/island/race children inherit that group.
    for pid in groups:
        if pid:
            with suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
    pool.kill_workers()
    stop_by = perf_counter() + 1.0
    for child in children:
        child.join(timeout=max(0.0, stop_by - perf_counter()))
    # Close the initializer-registration race: all direct workers have now
    # stopped, so no worker can create or register another session.
    for pid in groups:
        if pid:
            with suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
    if any(child.is_alive() for child in children):
        raise RuntimeError("audit workers did not stop within the bounded teardown")
    # All producer processes have exited. Half-close only our writer so a
    # manager blocked on a partial result receives EOF on its still-owned reader.
    if result_queue is not None:
        result_queue._writer.close()
    if manager is not None:
        manager.join(timeout=max(0.0, stop_by - perf_counter()))
        if manager.is_alive():
            raise RuntimeError("audit result manager did not stop within the bounded teardown")


def _run_jobs(
    jobs: list[Job],
    *,
    workers: int,
    deadline: float,
    publish: Callable[[Result], None],
) -> dict[int, Result]:
    """Own selected-job outcomes from URL preparation through process teardown."""
    terminal: dict[int, Result] = {}
    context = mp.get_context("spawn")
    groups = cast(MutableSequence[int], context.RawArray("q", workers))
    started = cast(MutableSequence[int], context.RawArray("b", len(jobs)))
    by_url: dict[str, list[int]] = {}
    for job_id, job in enumerate(jobs):
        by_url.setdefault(job.url, []).append(job_id)

    def settle(job_id: int, result: Result) -> None:
        if job_id in terminal:
            raise RuntimeError(f"duplicate terminal audit job: {job_id}")
        if result.job != jobs[job_id]:
            result = Result(
                jobs[job_id],
                "CRASH",
                "?",
                "worker returned a different selected job",
                ("<crash>",),
                0.0,
            )
        terminal[job_id] = result
        publish(result)

    def failed_url(url: str, exc: Exception) -> None:
        for job_id in by_url[url]:
            settle(
                job_id,
                Result(
                    jobs[job_id],
                    "SPEC",
                    "?",
                    f"{type(exc).__name__}: {exc}",
                    (),
                    0.0,
                ),
            )

    if time.monotonic() < deadline:
        if os.name != "posix":
            raise RuntimeError("hard audit process caps require POSIX process-group ownership")
        prior_children = frozenset(
            child.pid for child in mp.active_children() if child.pid is not None
        )
        pool = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_initialize_audit_worker,
            initargs=(groups, context.Lock(), started),
        )
        preparing: dict[Future[catalog.BeltAltitudeRules], str] = {}
        running: dict[Future[Result], int] = {}

        def harvest(future: Future[Result]) -> None:
            job_id = running.pop(future)
            try:
                result = future.result()
            except Exception as exc:  # Worker failure is an outcome, not a lost row.
                result = Result(
                    jobs[job_id],
                    "CRASH",
                    "?",
                    f"{type(exc).__name__}: {exc}",
                    ("<crash>",),
                    0.0,
                )
            settle(job_id, result)

        try:
            for url in by_url:
                if time.monotonic() >= deadline:
                    break
                try:
                    preparing[pool.submit(_belt_rules_for, url)] = url
                except Exception as exc:
                    failed_url(url, exc)
            while preparing or running:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                finished, _ = wait(
                    cast(
                        "tuple[Future[catalog.BeltAltitudeRules | Result], ...]",
                        (*preparing, *running),
                    ),
                    timeout=left,
                    return_when=FIRST_COMPLETED,
                )
                for future in finished:
                    if future in running:
                        harvest(cast(Future[Result], future))
                        continue
                    prepared = cast(Future[catalog.BeltAltitudeRules], future)
                    url = preparing.pop(prepared)
                    try:
                        rules = prepared.result()
                    except Exception as exc:
                        failed_url(url, exc)
                        continue
                    for job_id in by_url[url]:
                        if time.monotonic() >= deadline:
                            break
                        try:
                            running[pool.submit(_run_started_cell, job_id, jobs[job_id], rules)] = (
                                job_id
                            )
                        except Exception as exc:
                            settle(
                                job_id,
                                Result(
                                    jobs[job_id],
                                    "CRASH",
                                    "?",
                                    f"{type(exc).__name__}: {exc}",
                                    ("<crash>",),
                                    0.0,
                                ),
                            )
            # A wait timeout is not a reliable terminal snapshot. Harvest every
            # already-published result once before terminating outstanding work.
            for completed_future in tuple(running):
                if completed_future.done():
                    harvest(completed_future)
            for prepared, url in preparing.items():
                if prepared.done():
                    try:
                        prepared.result()
                    except Exception as exc:
                        failed_url(url, exc)
        finally:
            _stop_audit_workers(pool, groups, prior_children)

    for job_id, job in enumerate(jobs):
        if job_id not in terminal:
            status = "TERMINATED" if started[job_id] else "NOT_RUN"
            settle(
                job_id,
                Result(
                    job,
                    status,
                    "?",
                    "whole-audit cap exhausted",
                    (),
                    0.0,
                ),
            )
    return terminal


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
    ap.add_argument("--power-tower", choices=tuple(catalog.POWER_TOWER_CHOICES), default=None)
    ap.add_argument(
        "--machine-rank",
        choices=[rank.value for rank in MachineRank],
        default=MachineRank.EXACT.value,
        help="how to read the URL's machine rank (default: exact)",
    )
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
        help="hard cap including preparation and nested layout work; outstanding "
        "jobs report TERMINATED or NOT_RUN, followed by bounded process teardown",
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
    t0 = time.monotonic()
    ap = build_parser()
    args = ap.parse_args()
    global _COMMIT
    deadline = t0 + args.max_seconds
    _COMMIT = _head_commit(timeout_s=deadline - time.monotonic())
    _JSONL.clear()
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
        machine_rank=args.machine_rank,
        only=only,
        skip=skip,
        arrangements=args.arrangements,
        power_tower=args.power_tower,
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
    done = 0

    def publish(result: Result) -> None:
        nonlocal done
        if result.status not in {"TERMINATED", "NOT_RUN"}:
            done += 1
        record(tallies, result)
        _echo(result, done, len(jobs), time.monotonic() - t0)

    terminal = _run_jobs(jobs, workers=jobs_n, deadline=deadline, publish=publish)
    terminated = sum(result.status == "TERMINATED" for result in terminal.values())
    unreached = sum(result.status == "NOT_RUN" for result in terminal.values())
    if terminated or unreached:
        print(
            f"\n!! WALL-CLOCK CAP HIT at {args.max_seconds:g}s with "
            f"{terminated} cells terminated and {unreached} unreached.",
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
