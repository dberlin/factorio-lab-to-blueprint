"""Submit-and-poll, because a build is seconds to minutes.

``--budget`` is per layout and ``best`` lays out every candidate with every
active production strategy. Unpinned web requests run those independent
candidate races concurrently under one bounded CPU allowance; their aggregate
solver work is still ``candidates × strategies × budget``. A synchronous
request would still look like a hang to browsers and proxies, and a connection
dying would take the result with it.
So a build is a job -- submitted, then polled.

One submitted job runs at a time by default, deliberately. Inside that job the
pipeline caps its default aggregate solver budget at 16 CPUs from the process
affinity set, divides that budget across a bounded candidate pool, and each
candidate divides its share between the two strategy racers. Running separate
jobs concurrently would oversubscribe that allowance, so the outer queue
remains the honest answer: a job that waits says so, with its position.
"""

from __future__ import annotations

import math
import multiprocessing
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal, cast
from urllib.parse import urlsplit

from flab2bp import pipeline
from flab2bp.layout.band_policy import BAND_SELECTIONS, BandPolicy, BandSelection
from flab2bp.layout.base import (
    ATOMIC_COMPLETION_GRACE_S,
    LayoutAttemptFailure,
    NoValidLayout,
    PlacementStats,
)
from flab2bp.layout.observe import SearchObserver
from flab2bp.layout.observe_channel import (
    TRACE_QUEUE_MAXSIZE,
    close_trace_queue,
    finish_trace_producers,
    prepare_trace_queue,
)
from flab2bp.layout.strategy_race import RACE_COMPLETION_GRACE_S
from flab2bp.rates import DEFAULT_CANDIDATE_POLICIES, CandidatePolicy
from flab2bp.rates.adjust import ProliferatorTier
from flab2bp.rates.machine_choice import MachineRank
from flab2bp.web.payload import Json, JsonValue, describe, projection_failure, refusal
from flab2bp.web.trace import TraceCollector, TraceRing

State = Literal["queued", "running", "done", "refused", "error"]
WebStrategyName = Literal["best", "freeform", "sequence-pair", "hierarchical"]

#: The projected total, in seconds, past which a submitted job says out loud
#: that it will take a while.  This is a WARNING and not a bound: how long to
#: search is the caller's call, and a build that was asked for is run.  It is
#: compared against ``effective candidates * strategies * (budget + grace)``,
#: because that product is what actually runs.
WARN_TOTAL_SECONDS = 300.0

#: Jobs kept after they finish, so a poll that arrives late still finds its
#: answer.  Oldest finished job is evicted first.
HISTORY = 32


@dataclass(frozen=True, slots=True)
class Options:
    """One build request, already validated."""

    url: str
    #: Public and CLI callers share the same production strategy set.
    strategy: WebStrategyName = "best"
    band: BandSelection = "portable"
    candidate_policies: tuple[CandidatePolicy, ...] = DEFAULT_CANDIDATE_POLICIES
    budget_s: float = 15.0
    proliferator_tier: ProliferatorTier | None = None
    machine_rank: MachineRank = MachineRank.EXACT
    power_tower: str | None = None
    name: str = ""
    #: Mirrors ``--allow-invalid``.  Off by default: a blueprint that pastes
    #: cleanly and then does not run is the worst outcome available here.
    allow_invalid: bool = False
    #: A FactorioLab flow export, as the CSV text itself.  This is ``--flow``:
    #: the CLI names a file, a browser pastes or uploads one, and both end at
    #: the same ``flow_from_text`` with the same provenance check against the
    #: URL.  Empty means the recipe selection is DERIVED, which the report says
    #: rather than leaving it to be inferred.
    flow: str = ""
    #: Ask the server to drive FactorioLab and capture its CSV export.  This is
    #: allowed only for the validated FactorioLab HTTPS pages.
    fetch_flow: bool = False
    #: Stream search snapshots to the caller.  OFF by default: a picture of the
    #: search is a debugging instrument, and every build paying for one is not
    #: a trade anybody asked for.
    trace: bool = False

    @property
    def effective_candidate_count(self) -> int:
        """Candidates this request executes after flow pinning."""
        return 1 if self.flow.strip() or self.fetch_flow else len(self.candidate_policies)

    @property
    def solver_ceiling_s(self) -> float:
        """An upper bound on the LAYOUT solving this job will do.

        It bounds the search budgets only: parsing the URL, solving rates,
        emission, validation and encoding are all on top. The UI shows elapsed
        time against this so "still working" has a scale, not so it can promise
        an exact finish time.
        """
        return self.attempt_count * self.budget_s

    @property
    def attempt_count(self) -> int:
        """Layout attempts this job runs: one per candidate per strategy."""
        per_spec = pipeline.PRODUCTION_STRATEGY_COUNT if self.strategy == "best" else 1
        return self.effective_candidate_count * per_spec

    @property
    def completion_grace_s(self) -> float:
        """What one attempt gets on top of its search budget, in seconds.

        The budget bounds the SEARCH.  Compaction, projection, validation and
        encoding run after it inside the attempt's own hard wall, and that wall
        is budget + grace -- see ``pipeline``'s ``attempt_deadline``.  ``best``
        is submitted raced, so it carries the race's grace; an explicit
        strategy solves serially and carries the atomic one.
        """
        return RACE_COMPLETION_GRACE_S if self.strategy == "best" else ATOMIC_COMPLETION_GRACE_S

    @property
    def projected_total_s(self) -> float:
        """An upper bound on the WHOLE job's solving, in seconds.

        ``solver_ceiling_s`` counts search budgets alone; this adds the
        completion grace every attempt may also spend, which is what makes the
        difference between "15s" and most of an hour once the candidate and
        strategy multipliers land on it.  Rates, encoding and queueing are
        still on top: it is a scale for the wait, not a finish time.
        """
        return self.attempt_count * (self.budget_s + self.completion_grace_s)

    @property
    def warning(self) -> str | None:
        """What is worth saying out loud about this request, if anything.

        A long budget is not an error -- nothing is clamped and nothing is
        refused -- but the multiplication that turns a per-layout number into
        the job's wall clock is easy to miss, so it is spelled out.
        """
        if self.projected_total_s <= WARN_TOTAL_SECONDS:
            return None
        return (
            f"{self.effective_candidate_count} candidate(s) x {self.strategy} at "
            f"{self.budget_s:g}s per layout is up to {self.projected_total_s:g}s of "
            f"solving -- {self.attempt_count} layout(s) x ({self.budget_s:g}s budget + "
            f"{self.completion_grace_s:g}s completion grace) -- over the "
            f"{WARN_TOTAL_SECONDS:g}s mark. It will still run."
        )


class InvalidOptions(ValueError):
    """The request could not be turned into a build."""


def _validate_web_fetch_url(url: str) -> None:
    if "\\" in url:
        raise InvalidOptions(
            "automatic flow fetch requires a FactorioLab HTTPS /dsp/list or /dsp/flow URL"
        )
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise InvalidOptions(
            "automatic flow fetch requires a FactorioLab HTTPS /dsp/list or /dsp/flow URL"
        ) from exc
    if (
        parsed.scheme != "https"
        or hostname != "factoriolab.github.io"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("/dsp/list", "/dsp/flow")
    ):
        raise InvalidOptions(
            "automatic flow fetch requires a FactorioLab HTTPS /dsp/list or /dsp/flow URL"
        )


def parse_options(raw: JsonValue) -> Options:
    """Validate a decoded JSON body into :class:`Options`.

    Every bound here is a refusal rather than a clamp.  Silently rounding a
    budget of 9999 down to something servable would run a different build from
    the one that was asked for and report it as the one that was asked for.

    The budget itself has no upper bound for that same reason: how long to
    search is the caller's call.  It must be a positive finite number, and a
    projected total over :data:`WARN_TOTAL_SECONDS` comes back as
    :attr:`Options.warning` -- carried on the job, never raised.
    """
    if not isinstance(raw, dict):
        raise InvalidOptions("expected a JSON object")

    allowed = {
        "url",
        "strategy",
        "band",
        "candidate_policies",
        "budget_s",
        "proliferator_tier",
        "machine_rank",
        "power_tower",
        "name",
        "allow_invalid",
        "flow",
        "fetch_flow",
        "trace",
    }
    unknown = sorted(raw.keys() - allowed)
    if unknown:
        names = ", ".join(f"'{name}'" for name in unknown)
        raise InvalidOptions(f"unknown option(s): {names}")

    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        raise InvalidOptions("'url' is required")

    strategy = raw.get("strategy", "best")
    match strategy:
        case "best" | "freeform" | "sequence-pair" | "hierarchical":
            web_strategy: WebStrategyName = strategy
        case _:
            raise InvalidOptions(
                "'strategy' must be one of best, freeform, sequence-pair, hierarchical"
            )

    raw_band = raw.get("band", "portable")
    if not isinstance(raw_band, str):
        raise InvalidOptions("'band' must be one of " + ", ".join(BAND_SELECTIONS))
    try:
        band: BandSelection = BandPolicy.parse(raw_band).selection
    except ValueError as exc:
        raise InvalidOptions("'band' must be one of " + ", ".join(BAND_SELECTIONS)) from exc

    raw_candidate_policies = raw.get(
        "candidate_policies",
        [policy.value for policy in DEFAULT_CANDIDATE_POLICIES],
    )
    if not isinstance(raw_candidate_policies, list) or not raw_candidate_policies:
        raise InvalidOptions("'candidate_policies' must be a non-empty array of named policies")
    selected_policies: set[CandidatePolicy] = set()
    for value in raw_candidate_policies:
        if not isinstance(value, str):
            raise InvalidOptions(f"'candidate_policies' contains an unknown policy: {value!r}")
        try:
            policy = CandidatePolicy(value)
        except ValueError as exc:
            raise InvalidOptions(
                f"'candidate_policies' contains an unknown policy: {value!r}"
            ) from exc
        if policy in selected_policies:
            raise InvalidOptions("'candidate_policies' must not contain duplicate policies")
        selected_policies.add(policy)
    candidate_policies = tuple(
        policy for policy in DEFAULT_CANDIDATE_POLICIES if policy in selected_policies
    )

    raw_budget = raw.get("budget_s", 15.0)
    if isinstance(raw_budget, bool) or not isinstance(raw_budget, (int, float)):
        raise InvalidOptions("'budget_s' must be a positive finite number")
    try:
        budget = float(raw_budget)
    except OverflowError as exc:
        raise InvalidOptions("'budget_s' must be a positive finite number") from exc
    if not math.isfinite(budget) or budget <= 0:
        raise InvalidOptions("'budget_s' must be a positive finite number")
    raw_tier = raw.get("proliferator_tier", "auto")
    match raw_tier:
        case "auto" | None:
            proliferator_tier = None
        case "none":
            proliferator_tier = ProliferatorTier.NONE
        case "1":
            proliferator_tier = ProliferatorTier.MK1
        case "2":
            proliferator_tier = ProliferatorTier.MK2
        case "3":
            proliferator_tier = ProliferatorTier.MK3
        case _:
            raise InvalidOptions("'proliferator_tier' must be one of auto, none, 1, 2, 3")
    raw_rank = raw.get("machine_rank", MachineRank.EXACT.value)
    match raw_rank:
        case "exact" | None:
            machine_rank = MachineRank.EXACT
        case "up-to":
            machine_rank = MachineRank.UP_TO
        case _:
            raise InvalidOptions("'machine_rank' must be one of exact, up-to")

    raw_power_tower = raw.get("power_tower", "auto")
    if raw_power_tower is None or raw_power_tower == "auto":
        power_tower = None
    elif isinstance(raw_power_tower, str) and raw_power_tower in pipeline.POWER_TOWER_CHOICES:
        power_tower = raw_power_tower
    else:
        raise InvalidOptions(
            "'power_tower' must be one of auto, " + ", ".join(pipeline.POWER_TOWER_CHOICES)
        )

    allow_invalid = raw.get("allow_invalid", False)
    if not isinstance(allow_invalid, bool):
        raise InvalidOptions("'allow_invalid' must be a boolean")

    name = raw.get("name", "")
    if not isinstance(name, str):
        raise InvalidOptions("'name' must be a string")

    flow = raw.get("flow", "")
    if not isinstance(flow, str):
        raise InvalidOptions("'flow' must be a string: a FactorioLab flow export's CSV text")

    fetch_flow = raw.get("fetch_flow", False)
    if not isinstance(fetch_flow, bool):
        raise InvalidOptions("'fetch_flow' must be a boolean")
    if fetch_flow and flow.strip():
        raise InvalidOptions("'flow' and 'fetch_flow' are mutually exclusive")
    if fetch_flow:
        _validate_web_fetch_url(url.strip())

    trace = raw.get("trace", False)
    if not isinstance(trace, bool):
        raise InvalidOptions("'trace' must be a boolean")

    return Options(
        url=url.strip(),
        strategy=web_strategy,
        band=band,
        candidate_policies=candidate_policies,
        budget_s=budget,
        proliferator_tier=proliferator_tier,
        machine_rank=machine_rank,
        power_tower=power_tower,
        name=name,
        allow_invalid=allow_invalid,
        flow=flow.strip(),
        fetch_flow=fetch_flow,
        trace=trace,
    )


@dataclass
class Job:
    """A submitted build and whatever is known about it so far."""

    id: str
    options: Options
    submitted_at: float
    state: State = "queued"
    started_at: float | None = None
    finished_at: float | None = None
    #: The described build, on ``done``.
    result: Json | None = None
    #: The refusal, on ``refused`` -- a result with reasons, not a failure.
    refusal: Json | None = None
    #: The message, on ``error``.
    error: str | None = None
    #: The last thing ``pipeline.build`` said it was doing.  ``None`` until the
    #: first pair starts -- parsing the URL and solving the rates happen before
    #: any layout does, and claiming "candidate 1 of 6" during them would be a
    #: guess dressed as a fact.
    progress: pipeline.AttemptProgress | None = None
    #: Every pair that has settled, newest last.  Kept because "sequence-pair
    #: refused this candidate 40 seconds ago" is worth seeing while the next
    #: one runs, not only in the report at the end.
    settled: list[pipeline.AttemptProgress] = field(default_factory=list)
    #: The collector for this job's search trace, or ``None`` when trace was
    #: never asked for.  Set once, under ``_lock``, before the solve starts.
    trace: TraceCollector | None = None
    #: Every raced leg's OWN ``TraceChannel``-side drop count (a transiently
    #: full queue, or an unpicklable event -- Ruling 4), summed once the build
    #: settles. ``collector.dropped`` only ever sees the PARENT side (ring and
    #: stage-1 eviction); without this the web ``dropped`` figure is silently
    #: half the truth (fix round 1, Important 5).
    leg_trace_dropped: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def elapsed_s(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.finished_at or time.monotonic()) - self.started_at

    @property
    def done(self) -> bool:
        return self.state in ("done", "refused", "error")


def run_build(
    options: Options,
    on_progress: pipeline.ProgressSink,
    search_observer: SearchObserver | None = None,
    trace_queue: object | None = None,
) -> pipeline.Build:
    """Run one build through the pipeline's shared CPU-allocation policy.

    ``--flow`` arrives as CSV text and goes through ``flow_from_text``'s
    provenance check exactly as a file named on the command line does.
    ``--fetch-flow`` is admitted only for the strict FactorioLab HTTPS
    allowlist, and request-stage CDP interception aborts a forbidden main-frame
    document redirect before Chromium accesses it.

    ``sequence_islands`` is deliberately NOT passed: the web UI has no control
    for it, so it takes ``pipeline.resolve_sequence_islands``' default like any
    other caller that has no opinion.  Passing 1 here would be the one line
    that quietly kept the browser on a single core.

    ``trace_queue`` is ``search_observer``'s companion for a RACED leg (Task 8
    fix round 1): a raced arm runs in a spawned child and has no in-process
    observer to call at all, so this is its only route to the parent. The
    caller (:meth:`Builder._run`) creates and owns it -- see there for why.
    """
    return pipeline.build(
        options.url,
        strategy=options.strategy,
        band=options.band,
        candidate_policies=options.candidate_policies,
        time_budget_s=options.budget_s,
        proliferator_tier=options.proliferator_tier,
        machine_rank=options.machine_rank,
        power_tower=options.power_tower,
        name=options.name,
        flow_text=options.flow or None,
        fetch_flow=options.fetch_flow,
        fetch_url_validator=_validate_web_fetch_url if options.fetch_flow else None,
        on_progress=on_progress,
        search_observer=search_observer,
        trace_queue=trace_queue,
        race=options.strategy == "best",
    )


#: What a :class:`Builder` runs.  The progress sink is a parameter rather than
#: something the builder reaches in and sets, so a test can substitute a solve
#: that reports whatever sequence it wants to see rendered.
Solve = Callable[
    [Options, pipeline.ProgressSink, SearchObserver | None, object | None], pipeline.Build
]


class Builder:
    """A queue of builds and the answers they produced."""

    def __init__(
        self,
        *,
        workers: int = 1,
        history: int = HISTORY,
        solve: Solve = run_build,
    ) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="flab2bp-build")
        self._solve = solve
        self._history = history
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, Job] = OrderedDict()

    def submit(self, options: Options) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], options=options, submitted_at=time.monotonic())
        with self._lock:
            self._jobs[job.id] = job
            self._evict()
        self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def queue_position(self, job: Job) -> int:
        """How many jobs are ahead of this one, 0 when it is next or running."""
        with self._lock:
            waiting = [j for j in self._jobs.values() if j.state == "queued"]
        return sum(1 for j in waiting if j.submitted_at < job.submitted_at)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _evict(self) -> None:
        """Drop finished jobs only after their trace reader has settled."""
        finished = [
            jid
            for jid, job in self._jobs.items()
            if job.done and (job.trace is None or job.trace.closed or job.trace.error is not None)
        ]
        while len(self._jobs) > self._history and finished:
            del self._jobs[finished.pop(0)]

    def _run(self, job: Job) -> None:
        with job._lock:
            job.state = "running"
            job.started_at = time.monotonic()

        def note(step: pipeline.AttemptProgress) -> None:
            # Called from the solve thread; a poll reads it from another.
            with job._lock:
                job.progress = step
                if step.phase != "started":
                    job.settled.append(step)

        collector: TraceCollector | None = None
        # The parent's read end of a raced build's child-to-parent trace
        # queue, or `None` when trace is off. Created and OWNED here (fix
        # round 1): this is a long-lived web process, so whichever module
        # creates a `multiprocessing.Queue` must be the one that closes it --
        # `pipeline.build` no longer creates one itself, precisely so a build
        # that starts and ends inside one call is never left holding a
        # resource meant to outlive it. The SAME object is handed to both
        # `TraceCollector` (which drains it on its own daemon thread, live,
        # not just when a candidate settles) and `run_build` (which forwards
        # it to whichever leg actually races).
        trace_queue: object | None = None
        try:
            try:
                # Constructed and started inside the try: if `collector.start()`
                # ever raises (e.g. thread exhaustion), the job must still reach
                # a terminal state rather than getting stuck in "running"
                # forever with `_run` propagating past its own caller.
                if job.options.trace:
                    trace_queue = multiprocessing.get_context("spawn").Queue(
                        maxsize=TRACE_QUEUE_MAXSIZE
                    )
                    prepare_trace_queue(trace_queue)
                    collector = TraceCollector(
                        TraceRing(), started_at=time.monotonic(), queue=trace_queue
                    )
                    collector.start()
                    with job._lock:
                        job.trace = collector
                build = self._solve(
                    job.options,
                    note,
                    None if collector is None else collector.observer,
                    trace_queue,
                )
                result = describe(build, allow_invalid=job.options.allow_invalid)
            except NoValidLayout as exc:
                # Not an error. A spec nobody can lay out reports which pairs
                # were tried and why each gave up, and that is the most useful
                # thing on the screen when it happens.
                failures = _attempt_failures(exc)
                with job._lock:
                    job.state = "refused"
                    job.refusal = refusal(failures, message=str(exc))
                    job.leg_trace_dropped = _sum_trace_dropped(f.stats for f in failures)
                    job.finished_at = time.monotonic()
            except (ValueError, KeyError) as exc:
                with job._lock:
                    job.state = "error"
                    job.error = str(exc)
                    job.finished_at = time.monotonic()
            except Exception:
                # Chromium/CDP failures are ordinary operational failures for a
                # job. Exception deliberately excludes KeyboardInterrupt and
                # SystemExit.
                with job._lock:
                    job.state = "error"
                    job.error = "build failed unexpectedly"
                    job.finished_at = time.monotonic()
            else:
                with job._lock:
                    job.state = "done"
                    job.leg_trace_dropped = _sum_trace_dropped(
                        a.placement.stats for a in build.attempts
                    ) + _sum_trace_dropped(f.stats for f in build.refused)
                    job.result = result
                    job.finished_at = time.monotonic()
        finally:
            # Every candidate race has released its children and feeders,
            # including normal process exits that abandon a buffered trace.
            # Close only the write end: native receive state distinguishes
            # clean exhaustion from interrupted framing while the reader drains.
            finish_trace_producers(trace_queue)
            if collector is not None and not collector.stop():
                collector.stop(timeout=None)
            if trace_queue is not None:
                close_trace_queue(trace_queue)

    def snapshot(self, job: Job) -> Json:
        """The job as JSON, including where it is if it is not finished."""
        with job._lock:
            settled: list[JsonValue] = [_step(step) for step in job.settled]
            body: Json = {
                "id": job.id,
                "state": job.state,
                "elapsed_s": round(job.elapsed_s, 2),
                # A ceiling on solver time, not a promise of a finish time --
                # see Options.solver_ceiling_s.
                "solver_ceiling_s": job.options.solver_ceiling_s,
                # A long budget is honoured, not clamped, so the only honest
                # thing left to do is say what it will cost. `null` when the
                # projected total is unremarkable -- a warning that is always
                # present is one nobody reads.
                "warning": job.options.warning,
                "options": {
                    "url": job.options.url,
                    "strategy": job.options.strategy,
                    "band": job.options.band,
                    "candidate_policies": [
                        policy.value for policy in job.options.candidate_policies
                    ],
                    "budget_s": job.options.budget_s,
                    "power_tower": job.options.power_tower or "auto",
                    "proliferator_tier": (
                        job.options.proliferator_tier.value
                        if job.options.proliferator_tier is not None
                        else "auto"
                    ),
                    "machine_rank": job.options.machine_rank.value,
                    "allow_invalid": job.options.allow_invalid,
                    "name": job.options.name,
                    # The CSV itself is not echoed -- it is up to 256kB and the
                    # page already has it. Whether one was supplied is the fact
                    # a poller needs, and `result.flow_pinned` is the proof it
                    # was honoured.
                    "flow_supplied": bool(job.options.flow),
                    "trace": job.options.trace,
                },
                "result": job.result,
                "refusal": job.refusal,
                "error": job.error,
                # Real progress, not elapsed time: `pipeline.build` says which
                # pair it is on. Absent until the first layout starts, because
                # the URL parse and the rate solve come first and nothing knows
                # how long they take.
                "progress": _step(job.progress),
                "settled": settled,
            }
        if job.state == "queued":
            body["queue_position"] = self.queue_position(job)
        return body

    def trace_page(self, job: Job, cursor: int) -> Json:
        """The frames after ``cursor``, or an empty page when trace is off."""
        with job._lock:
            collector = job.trace
            done = job.done
        if collector is None:
            return {"frames": [], "next": cursor, "dropped": 0, "evicted": 0, "complete": done}
        # Observe closure BEFORE the ring snapshot. Reading it afterwards could
        # miss a final append between an empty snapshot and closure publication.
        closed = collector.closed
        error = collector.error
        frames, nxt = collector.ring.since(cursor)
        if not frames and error is not None:
            return {"error": error}
        return {
            "frames": cast(JsonValue, frames),
            "next": nxt,
            # `collector.dropped` is GENUINE loss only -- stage-1 overflow at
            # this process -- it knows nothing about a raced leg's OWN
            # `TraceChannel` dropping a frame before it ever reached this
            # process. Without `job.leg_trace_dropped`, a saturated queue
            # (Criticals C1/C2) would report a drop count that is honest but
            # incomplete, and Ruling 4 is exactly the case where that
            # difference is a structural failure, not noise.
            "dropped": collector.dropped + job.leg_trace_dropped,
            # The ring's OWN eviction (fix round, Important 6): a bounded
            # window doing its job -- keeping the newest frames -- on any
            # build past `TRACE_RING_FRAMES`, and reported here as a distinct,
            # non-alarming figure rather than folded into `dropped` where it
            # would read as data the search lost.
            "evicted": collector.ring.dropped,
            "complete": closed and not frames,
        }


def _sum_trace_dropped(stats_sources: Iterable[PlacementStats]) -> int:
    """Fold every attempt/failure's own ``trace_dropped`` into one total."""
    return sum(int(stats.get("trace_dropped", 0)) for stats in stats_sources)


def _step(step: pipeline.AttemptProgress | None) -> Json | None:
    """One :class:`~flab2bp.pipeline.AttemptProgress` as JSON, or nothing."""
    if step is None:
        return None
    return {
        "index": step.index,
        "total": step.total,
        "candidate": step.candidate,
        "strategy": step.strategy,
        "phase": step.phase,
        "area": step.area,
        "ok": step.ok,
        "reason": step.reason,
        "projection_failures": [
            projection_failure(failure) for failure in step.projection_failures
        ],
    }


def _attempt_failures(exc: NoValidLayout) -> tuple[LayoutAttemptFailure, ...]:
    """Return pipeline-provided attempt boundaries without parsing prose."""
    if exc.attempt_failures:
        return exc.attempt_failures
    reasons = exc.attempt_reasons or (exc.reason,)
    return tuple(
        LayoutAttemptFailure(
            exc.spec_label,
            None,
            reason,
            exc.projection_failures if len(reasons) == 1 else (),
            cast(PlacementStats, exc.stats),
        )
        for reason in reasons
    )
