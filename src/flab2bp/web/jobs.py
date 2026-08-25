"""Submit-and-poll, because a build is seconds to minutes.

``--budget`` is per layout and ``best`` lays out every candidate with both
strategies, so the wall clock is a multiple of it.  A request that waits for
that is a request that looks like a hang: browsers and proxies give up long
before a large spec does, and the connection dying takes the result with it.
So a build is a job -- submitted, then polled.

One worker by default, deliberately.  ``pyproject.toml`` already records what
happens when CP-SAT solves are run in parallel on this box: a single solve runs
at ~700% CPU, so N of them do not go N times faster, they each get a fraction of
the wall-clock budget they were promised and the whole set comes back worse.
A queue is the honest answer -- a job that waits says so, with its position.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

from flab2bp import pipeline
from flab2bp.layout.base import NoValidLayout
from flab2bp.web.payload import Json, describe, refusal

State = Literal["queued", "running", "done", "refused", "error"]

#: Strategies ``best`` will try.  Named here rather than imported so estimating
#: the ceiling never reaches into the layout package.
_STRATEGIES_FOR_BEST = 2

#: The most solver time one submitted job may ask for, in seconds.  This is a
#: ceiling on ``candidates * strategies * budget``, not on ``budget`` alone,
#: because that product is what actually runs: three candidates and both
#: strategies at a 60s budget is six minutes, not one.
MAX_SOLVER_SECONDS = 300.0

#: Jobs kept after they finish, so a poll that arrives late still finds its
#: answer.  Oldest finished job is evicted first.
HISTORY = 32


@dataclass(frozen=True, slots=True)
class Options:
    """One build request, already validated."""

    url: str
    strategy: str = "best"
    power: bool = True
    candidates: int = 3
    budget_s: float = 2.0
    name: str = ""
    #: Mirrors ``--allow-invalid``.  Off by default: a blueprint that pastes
    #: cleanly and then does not run is the worst outcome available here.
    allow_invalid: bool = False

    @property
    def solver_ceiling_s(self) -> float:
        """An upper bound on the LAYOUT solving this job will do.

        Deliberately not called an estimate.  It bounds the CP-SAT budgets only:
        parsing the URL, solving the rates, validating and encoding are all on
        top, and a strategy that refuses spends its retry budget as well.  The
        UI shows elapsed time against this so "still working" has a scale, not
        so it can promise a finish time.
        """
        per_spec = _STRATEGIES_FOR_BEST if self.strategy == "best" else 1
        return self.candidates * per_spec * self.budget_s


class InvalidOptions(ValueError):
    """The request could not be turned into a build."""


def parse_options(raw: object) -> Options:
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
    if strategy not in ("best", "spine", "freeform"):
        raise InvalidOptions("'strategy' must be one of best, spine, freeform")

    candidates = raw.get("candidates", 3)
    if not isinstance(candidates, int) or isinstance(candidates, bool) or not 1 <= candidates <= 8:
        raise InvalidOptions("'candidates' must be an integer from 1 to 8")

    budget = raw.get("budget_s", 2.0)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
        raise InvalidOptions("'budget_s' must be a positive number")

    power = raw.get("power", True)
    if not isinstance(power, bool):
        raise InvalidOptions("'power' must be a boolean")

    allow_invalid = raw.get("allow_invalid", False)
    if not isinstance(allow_invalid, bool):
        raise InvalidOptions("'allow_invalid' must be a boolean")

    name = raw.get("name", "")
    if not isinstance(name, str):
        raise InvalidOptions("'name' must be a string")

    options = Options(
        url=url.strip(),
        strategy=strategy,
        power=power,
        candidates=candidates,
        budget_s=float(budget),
        name=name,
        allow_invalid=allow_invalid,
    )
    if options.solver_ceiling_s > MAX_SOLVER_SECONDS:
        raise InvalidOptions(
            f"{options.candidates} candidate(s) x {options.strategy} at "
            f"{options.budget_s:g}s is up to {options.solver_ceiling_s:g}s of solving, "
            f"over the {MAX_SOLVER_SECONDS:g}s ceiling. Lower the budget or the "
            f"candidate count, or pick a single strategy."
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
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def elapsed_s(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.finished_at or time.monotonic()) - self.started_at

    @property
    def done(self) -> bool:
        return self.state in ("done", "refused", "error")


def run_build(options: Options) -> pipeline.Build:
    """The one call into the solver.

    ``--flow`` and ``--fetch-flow`` are deliberately not wired: the latter
    drives a headless browser, which is a much larger surface than a build, and
    the former needs a file upload.  The result says ``flow_pinned: false`` and
    the UI says what that means, rather than the omission reading as silence.
    """
    return pipeline.build(
        options.url,
        strategy=options.strategy,  # type: ignore[arg-type]
        power=options.power,
        candidates=options.candidates,
        time_budget_s=options.budget_s,
        name=options.name,
    )


class Builder:
    """A queue of builds and the answers they produced."""

    def __init__(
        self,
        *,
        workers: int = 1,
        history: int = HISTORY,
        solve: Callable[[Options], pipeline.Build] = run_build,
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
        try:
            build = self._solve(job.options)
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
                    "power": job.options.power,
                    "allow_invalid": job.options.allow_invalid,
                    "name": job.options.name,
                },
                "result": job.result,
                "refusal": job.refusal,
                "error": job.error,
            }
        if job.state == "queued":
            body["queue_position"] = self.queue_position(job)
        return body


def _reasons(exc: NoValidLayout) -> tuple[str, ...]:
    """The per-pair reasons the pipeline joined into one string.

    ``pipeline.build`` builds ``NoValidLayout``'s reason by ``"; ".join``-ing
    the refusals it collected, so splitting it back apart is how the UI gets one
    line per strategy/candidate pair rather than one long sentence.
    """
    return tuple(part.strip() for part in exc.reason.split(";") if part.strip())
