"""Submit-and-poll, because a build is seconds to minutes.

``--budget`` is per layout and ``best`` lays out every candidate with every
active production strategy, so the wall clock is a multiple of it.  A request
that waits for that is a request that looks like a hang: browsers and proxies
give up long before a large spec does, and the connection dying takes the
result with it.
So a build is a job -- submitted, then polled.

One worker by default, deliberately.  ``pyproject.toml`` already records what
happens when CP-SAT solves are run in parallel on this box: a single solve runs
at ~700% CPU, so N of them do not go N times faster, they each get a fraction of
the wall-clock budget they were promised and the whole set comes back worse.
A queue is the honest answer -- a job that waits says so, with its position.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from flab2bp import pipeline
from flab2bp.layout.base import NoValidLayout
from flab2bp.rates.adjust import ProliferatorTier
from flab2bp.web.payload import Json, JsonValue, describe, refusal

State = Literal["queued", "running", "done", "refused", "error"]
WebStrategyName = Literal["best", "freeform", "sequence-pair"]

#: The most solver time one submitted job may ask for, in seconds.  This is a
#: ceiling on ``candidates * strategies * budget``, because that product is
#: what actually runs.
MAX_SOLVER_SECONDS = 300.0

#: Jobs kept after they finish, so a poll that arrives late still finds its
#: answer.  Oldest finished job is evicted first.
HISTORY = 32


@dataclass(frozen=True, slots=True)
class Options:
    """One build request, already validated."""

    url: str
    #: Public and CLI callers share the same production strategy set.
    strategy: WebStrategyName = "best"
    power: bool = True
    candidates: int = 3
    budget_s: float = 15.0
    proliferator_tier: ProliferatorTier | None = None
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

    @property
    def solver_ceiling_s(self) -> float:
        """An upper bound on the LAYOUT solving this job will do.

        It bounds the search budgets only: parsing the URL, solving rates,
        emission, validation and encoding are all on top. The UI shows elapsed
        time against this so "still working" has a scale, not so it can promise
        an exact finish time.
        """
        per_spec = pipeline.PRODUCTION_STRATEGY_COUNT if self.strategy == "best" else 1
        return self.candidates * per_spec * self.budget_s


class InvalidOptions(ValueError):
    """The request could not be turned into a build."""


def _validate_web_fetch_url(url: str) -> None:
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise InvalidOptions(
            "automatic flow fetch requires a FactorioLab HTTPS /dsp/list or /dsp/flow URL"
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "factoriolab.github.io"
        or port not in (None, 443)
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
    """
    if not isinstance(raw, dict):
        raise InvalidOptions("expected a JSON object")

    url = raw.get("url")
    if not isinstance(url, str) or not url.strip():
        raise InvalidOptions("'url' is required")

    strategy = raw.get("strategy", "best")
    match strategy:
        case "best" | "freeform" | "sequence-pair":
            web_strategy: WebStrategyName = strategy
        case _:
            raise InvalidOptions("'strategy' must be one of best, freeform, sequence-pair")

    candidates = raw.get("candidates", 3)
    if not isinstance(candidates, int) or isinstance(candidates, bool) or not 1 <= candidates <= 8:
        raise InvalidOptions("'candidates' must be an integer from 1 to 8")

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

    power = raw.get("power", True)
    if not isinstance(power, bool):
        raise InvalidOptions("'power' must be a boolean")

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

    options = Options(
        url=url.strip(),
        strategy=web_strategy,
        power=power,
        candidates=candidates,
        budget_s=budget,
        proliferator_tier=proliferator_tier,
        name=name,
        allow_invalid=allow_invalid,
        flow=flow.strip(),
        fetch_flow=fetch_flow,
    )
    if options.solver_ceiling_s > MAX_SOLVER_SECONDS:
        raise InvalidOptions(
            f"{options.candidates} candidate(s) x {options.strategy} at "
            f"{options.budget_s:g}s is up to {options.solver_ceiling_s:g}s of solving, "
            f"over the {MAX_SOLVER_SECONDS:g}s ceiling. Lower the budget or the "
            f"candidate count, or pick an explicit strategy."
        )
    return options


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
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def elapsed_s(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.finished_at or time.monotonic()) - self.started_at

    @property
    def done(self) -> bool:
        return self.state in ("done", "refused", "error")


def run_build(options: Options, on_progress: pipeline.ProgressSink) -> pipeline.Build:
    """The one call into the solver.

    ``--flow`` arrives as CSV text and goes through ``flow_from_text``'s
    provenance check exactly as a file named on the command line does.
    ``--fetch-flow`` is admitted only for the strict FactorioLab HTTPS
    allowlist, and the same validator checks the browser's final main-frame
    location before any page probes run.
    """
    return pipeline.build(
        options.url,
        strategy=options.strategy,
        power=options.power,
        candidates=options.candidates,
        time_budget_s=options.budget_s,
        proliferator_tier=options.proliferator_tier,
        name=options.name,
        flow_text=options.flow or None,
        fetch_flow=options.fetch_flow,
        fetch_url_validator=_validate_web_fetch_url if options.fetch_flow else None,
        on_progress=on_progress,
    )


#: What a :class:`Builder` runs.  The progress sink is a parameter rather than
#: something the builder reaches in and sets, so a test can substitute a solve
#: that reports whatever sequence it wants to see rendered.
Solve = Callable[[Options, pipeline.ProgressSink], pipeline.Build]


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
        """Drop the oldest finished jobs. Never drops one still running."""
        finished = [jid for jid, j in self._jobs.items() if j.done]
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

        try:
            build = self._solve(job.options, note)
        except NoValidLayout as exc:
            # Not an error. A spec nobody can lay out reports which pairs were
            # tried and why each gave up, and that is the most useful thing on
            # the screen when it happens.
            with job._lock:
                job.state = "refused"
                job.refusal = refusal(list(_reasons(exc)), message=str(exc))
                job.finished_at = time.monotonic()
        except (ValueError, KeyError) as exc:
            with job._lock:
                job.state = "error"
                job.error = str(exc)
                job.finished_at = time.monotonic()
        else:
            with job._lock:
                job.state = "done"
                job.result = describe(build, allow_invalid=job.options.allow_invalid)
                job.finished_at = time.monotonic()

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
                "options": {
                    "url": job.options.url,
                    "strategy": job.options.strategy,
                    "candidates": job.options.candidates,
                    "budget_s": job.options.budget_s,
                    "proliferator_tier": (
                        job.options.proliferator_tier.value
                        if job.options.proliferator_tier is not None
                        else "auto"
                    ),
                    "power": job.options.power,
                    "allow_invalid": job.options.allow_invalid,
                    "name": job.options.name,
                    # The CSV itself is not echoed -- it is up to 256kB and the
                    # page already has it. Whether one was supplied is the fact
                    # a poller needs, and `result.flow_pinned` is the proof it
                    # was honoured.
                    "flow_supplied": bool(job.options.flow),
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
    }


def _reasons(exc: NoValidLayout) -> tuple[str, ...]:
    """The per-pair reasons the pipeline joined into one string.

    ``pipeline.build`` builds ``NoValidLayout``'s reason by ``"; ".join``-ing
    the refusals it collected, so splitting it back apart is how the UI gets one
    line per strategy/candidate pair rather than one long sentence.
    """
    return tuple(part.strip() for part in exc.reason.split(";") if part.strip())
