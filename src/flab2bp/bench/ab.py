"""The A-vs-B engine: is Strategy A or Strategy B denser, and by how much?

This module is the answer to a specific past failure.  An earlier comparison in
this project concluded "A wins, geometric mean 1.359" and it was an artifact:
the harness scored layouts the validator had rejected.  Invalid layouts are
**systematically smaller** -- an unrouted net is a belt run that does not exist,
so the broken layout has the tighter bounding box and wins on area.  One build
with 119 unrouted nets measured as the densest candidate on offer.

So the design here is not "collect numbers and average them".  It is a set of
structural guards, each one closing a way that conclusion could be reached
again:

1.  :class:`Sample` **cannot carry an area unless it is VALID.**  Not a
    convention, a constructor invariant -- ``__post_init__`` raises.  There is
    no code path that reads an area off a rejected layout, because such an
    object cannot be built.
2.  **Four ways to fail, kept apart.**  REFUSED (the strategy searched and found
    nothing: ``NoValidLayout``), INVALID (it produced something the validator
    rejected), ERROR (it crashed), CROSSFAIL (our validator liked it but the
    game's own format did not).  These call for different investigations and
    collapsing them hides whichever one is currently biting.
3.  **Every aggregate states its denominator.**  :class:`Comparison` cannot be
    rendered without coverage, and :meth:`Comparison.headline` prints coverage
    *before* the ratio.  "B is 1.2x denser" means nothing if B produced a layout
    for 3 of 12 specs and A for 11.
4.  **Coverage outranks density.**  A strategy that refuses half the corpus is
    not "denser", whatever the median of the other half says.
5.  **Spread is reported, never averaged away.**  The shipping default is
    multi-worker CP-SAT, deliberately nondeterministic (worth ~23% density over
    a single worker, so pinning it would measure a configuration neither
    strategy would ship).  A per-URL verdict whose A-spread and B-spread overlap
    is marked *not separated* and excluded from the headline count.

Everything here is pure and dependency-injected at the ``sample_once`` seam, so
the aggregation logic is unit-testable without running CP-SAT.
"""

from __future__ import annotations

import math
import multiprocessing
import resource
import statistics
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from enum import Enum

from flab2bp.bench.crossvalidate import CrossCheck, bun_available, crossvalidate, viewer_path
from flab2bp.bench.metrics import measure
from flab2bp.bench.scoring import DENSITY_DEADBAND, geometric_mean
from flab2bp.bench.types import Metrics
from flab2bp.layout.base import NoValidLayout, Placement


class Outcome(Enum):
    """What happened to one layout attempt.

    The four failure modes are deliberately distinct.  An earlier version of
    this comparison printed a single blank cell for all of them, which meant
    "the strategy has a structural gap" and "the strategy raised
    ``AttributeError``" looked identical in the table.
    """

    #: The strategy returned a placement, the validator accepted it, and the
    #: independent decoder (when available) round-tripped it.  Only VALID
    #: samples carry geometry.
    VALID = "valid"
    #: The strategy returned a placement and the validator rejected it.  Its
    #: area is deliberately not recorded -- see the module docstring.
    INVALID = "invalid"
    #: ``NoValidLayout``.  The strategy searched and found nothing routable.
    #: This is a *result*, not a crash: it is the honest behaviour that replaced
    #: the old fallback, and it must stay visible and stay separate.
    REFUSED = "refused"
    #: The strategy raised something that was not ``NoValidLayout``.  A bug in
    #: us, not a property of the spec.
    ERROR = "error"
    #: Our validator accepted it but encoding or the independent TypeScript
    #: decoder did not.  A layout the game's format rejects is not a win, so
    #: these are demoted out of VALID rather than counted.
    CROSSFAIL = "crossfail"


#: Order in which a failure is reported when a URL's candidates failed in
#: different ways.  Worst-news-first, measured by how much the failure indicts
#: *us* rather than the instance: a crash or a format rejection must never be
#: hidden behind a refusal that happened to also occur.
_SEVERITY: tuple[Outcome, ...] = (
    Outcome.CROSSFAIL,
    Outcome.ERROR,
    Outcome.INVALID,
    Outcome.REFUSED,
)


@dataclass(frozen=True, slots=True)
class Sample:
    """One ``(url, candidate, strategy, budget, trial)`` layout attempt.

    The invariant in ``__post_init__`` is the load-bearing part of this class:
    geometry and a blueprint exist **iff** the outcome is VALID.  That is what
    makes it impossible to reach the old artifact conclusion, because there is
    no object in the system that pairs a rejected layout with an area.
    """

    url_id: str
    candidate: str
    strategy: str
    budget_s: float
    trial: int
    outcome: Outcome
    seconds: float
    #: Measured from the buildings by :func:`flab2bp.bench.metrics.measure`,
    #: never read from ``Placement.stats`` -- a strategy reporting its own
    #: numbers is marking its own homework.  ``None`` unless VALID.
    metrics: Metrics | None = None
    #: Total buildings placed.  Not in ``Metrics`` (which counts by kind) but
    #: needed twice: it is what the independent decoder reports back, and it is
    #: what decides how unpleasant the blueprint is to paste.
    buildings: int = 0
    #: The encoded blueprint, for cross-validation.  Empty unless VALID.
    blueprint: str = ""
    #: Refusal reason, failing checks, or exception text.  Empty when VALID.
    detail: str = ""
    #: Process CPU consumed by this attempt. ``None`` only for legacy JSON.
    cpu_seconds: float | None = None
    #: Process peak resident set after this attempt, in MiB. ``None`` for legacy JSON.
    peak_rss_mb: float | None = None
    #: Power mode is part of the persisted sample identity.
    power: bool = False

    def __post_init__(self) -> None:
        valid = self.outcome is Outcome.VALID
        if valid and self.metrics is None:
            raise ValueError("a VALID sample must carry measured geometry")
        if not valid and self.buildings:
            raise ValueError("only a VALID sample may carry a building count")
        if not valid and self.metrics is not None:
            raise ValueError(
                f"a {self.outcome.value.upper()} sample must not carry geometry: "
                "invalid layouts are systematically smaller, so recording their "
                "area would reward dropping connections"
            )
        if not valid and self.blueprint:
            raise ValueError("only a VALID sample may carry a blueprint")

    @property
    def area(self) -> int | None:
        return self.metrics.area if self.metrics is not None else None

    def demoted(self, outcome: Outcome, detail: str) -> Sample:
        """Re-grade this sample, dropping its geometry.

        Used by cross-validation: a placement our validator liked but the game's
        format rejected stops being VALID, and its area stops counting, in one
        step that cannot forget the second half.
        """
        return replace(
            self, outcome=outcome, metrics=None, buildings=0, blueprint="", detail=detail
        )


def _peak_rss_mb() -> float:
    """Return process peak RSS in MiB on the platforms supported by the harness."""
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024


@dataclass(frozen=True, slots=True)
class MeasuredAttempt:
    """A layout result measured inside the process that performed the solve."""

    placement: Placement | None
    failure: Outcome | None
    detail: str
    seconds: float
    cpu_seconds: float
    peak_rss_mb: float


def measure_attempt(lay_out: Callable[[], Placement]) -> MeasuredAttempt:
    """Measure one solve in the current process, excluding caller overhead."""
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        placement = lay_out()
    except NoValidLayout as exc:
        return MeasuredAttempt(
            None,
            Outcome.REFUSED,
            exc.reason,
            time.perf_counter() - started,
            time.process_time() - cpu_started,
            _peak_rss_mb(),
        )
    except Exception as exc:  # noqa: BLE001 - one bad cell must not kill the sweep
        return MeasuredAttempt(
            None,
            Outcome.ERROR,
            f"{type(exc).__name__}: {exc}",
            time.perf_counter() - started,
            time.process_time() - cpu_started,
            _peak_rss_mb(),
        )
    return MeasuredAttempt(
        placement,
        None,
        "",
        time.perf_counter() - started,
        time.process_time() - cpu_started,
        _peak_rss_mb(),
    )


def isolated_attempt(lay_out: Callable[[], Placement]) -> MeasuredAttempt:
    """Measure one attempt in a newly spawned process with an uncontaminated RSS."""
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
        return pool.submit(measure_attempt, lay_out).result()


def sample_measured(
    *,
    url_id: str,
    candidate: str,
    strategy: str,
    budget_s: float,
    trial: int,
    attempt: MeasuredAttempt,
    judge: Callable[[Placement], tuple[bool, tuple[str, ...]]],
    encode: Callable[[Placement], str],
    power: bool = False,
) -> Sample:
    """Grade a measured attempt without changing its child-process resource data."""
    if attempt.failure is not None:
        return Sample(
            url_id,
            candidate,
            strategy,
            budget_s,
            trial,
            attempt.failure,
            attempt.seconds,
            detail=attempt.detail,
            cpu_seconds=attempt.cpu_seconds,
            peak_rss_mb=attempt.peak_rss_mb,
            power=power,
        )
    placement = attempt.placement
    if placement is None:
        raise AssertionError("a successful measured attempt must carry a placement")
    ok, checks = judge(placement)
    if not ok:
        return Sample(
            url_id,
            candidate,
            strategy,
            budget_s,
            trial,
            Outcome.INVALID,
            attempt.seconds,
            detail=",".join(checks) or "unknown check",
            cpu_seconds=attempt.cpu_seconds,
            peak_rss_mb=attempt.peak_rss_mb,
            power=power,
        )
    try:
        blueprint = encode(placement)
    except Exception as exc:  # noqa: BLE001
        return Sample(
            url_id,
            candidate,
            strategy,
            budget_s,
            trial,
            Outcome.CROSSFAIL,
            attempt.seconds,
            detail=f"encode: {type(exc).__name__}: {exc}",
            cpu_seconds=attempt.cpu_seconds,
            peak_rss_mb=attempt.peak_rss_mb,
            power=power,
        )
    return Sample(
        url_id,
        candidate,
        strategy,
        budget_s,
        trial,
        Outcome.VALID,
        attempt.seconds,
        metrics=measure(placement),
        buildings=len(placement.buildings),
        blueprint=blueprint,
        cpu_seconds=attempt.cpu_seconds,
        peak_rss_mb=attempt.peak_rss_mb,
        power=power,
    )


def sample_once(
    *,
    url_id: str,
    candidate: str,
    strategy: str,
    budget_s: float,
    trial: int,
    lay_out: Callable[[], Placement],
    judge: Callable[[Placement], tuple[bool, tuple[str, ...]]],
    encode: Callable[[Placement], str],
    power: bool = False,
) -> Sample:
    """Measure and grade one attempt in the current process."""
    return sample_measured(
        url_id=url_id,
        candidate=candidate,
        strategy=strategy,
        budget_s=budget_s,
        trial=trial,
        attempt=measure_attempt(lay_out),
        judge=judge,
        encode=encode,
        power=power,
    )


@dataclass(frozen=True, slots=True)
class CrossSummary:
    """What the independent TypeScript decoder said.

    ``available`` is reported first and separately on purpose: zero failures
    with the toolchain missing must never read as "everything passed".
    """

    available: bool
    checked: int = 0
    passed: int = 0
    demoted: tuple[str, ...] = ()
    reason: str = ""
    complete: bool = True

    def __post_init__(self) -> None:
        if type(self.available) is not bool:
            raise ValueError("cross-validation availability must be a bool")
        if type(self.complete) is not bool:
            raise ValueError("cross-validation completeness must be a bool")
        if any(type(value) is not int or value < 0 for value in (self.checked, self.passed)):
            raise ValueError("cross-validation counts must be non-negative integers")
        if self.passed > self.checked:
            raise ValueError("cross-validation passes cannot exceed checked blueprints")
        if not isinstance(self.demoted, tuple) or any(
            not isinstance(item, str) or not item for item in self.demoted
        ):
            raise ValueError("cross-validation demotions must be non-empty strings in a tuple")
        if not isinstance(self.reason, str):
            raise ValueError("cross-validation reason must be a string")

    def summary(self) -> str:
        if not self.available:
            return f"cross-validation SKIPPED ({self.reason or 'toolchain missing'})"
        if not self.checked:
            return "cross-validation ran but had no valid blueprints to check"
        return (
            f"cross-validation: {self.passed}/{self.checked} blueprints decoded "
            f"with a valid MD5F hash and a matching building count"
            + (f"; {len(self.demoted)} demoted out of VALID" if self.demoted else "")
        )


def cross_verdict(check: CrossCheck, sample: Sample) -> str:
    """Empty string when the blueprint is good, else why it is not."""
    if not check.ok:
        return f"decode failed: {check.error or 'unknown'}"
    if not check.hash_valid:
        return "MD5F hash invalid"
    expected = sample.buildings
    if expected and check.buildings != expected:
        # The decoder counting a different number of buildings than we placed
        # means the encoder dropped or duplicated something -- which our own
        # validator cannot see, because it validates the Placement, not the
        # bytes.  This is the whole reason for having a second implementation.
        return f"building count {check.buildings} != placed {expected}"
    return ""


def crossvalidate_samples(
    samples: Sequence[Sample], *, strict: bool = False
) -> tuple[list[Sample], CrossSummary]:
    """Decode every VALID blueprint with the viewer's decoder; demote failures.

    One subprocess for the whole run.  A blueprint that does not survive the
    round trip is demoted to CROSSFAIL, which drops its area -- so a layout the
    game's format rejects cannot contribute to a density claim.
    """
    valid = [s for s in samples if s.outcome is Outcome.VALID and s.blueprint]
    if not valid:
        return list(samples), CrossSummary(available=True, checked=0)

    if viewer_path() is None or not bun_available():
        missing = "bun not on PATH" if not bun_available() else "no dsp-blueprint-viewer checkout"
        return list(samples), CrossSummary(available=False, reason=missing)

    checks = crossvalidate([s.blueprint for s in valid], strict=strict)
    if len(checks) != len(valid):
        return list(samples), CrossSummary(
            available=False,
            reason=f"bridge returned {len(checks)} verdicts for {len(valid)} blueprints",
        )

    verdicts = {id(s): cross_verdict(c, s) for s, c in zip(valid, checks, strict=True)}
    out: list[Sample] = []
    demoted: list[str] = []
    for s in samples:
        why = verdicts.get(id(s), "")
        if why:
            demoted.append(f"{s.url_id}/{s.candidate}/{s.strategy}: {why}")
            out.append(s.demoted(Outcome.CROSSFAIL, why))
        else:
            out.append(s)
    return out, CrossSummary(
        available=True,
        checked=len(valid),
        passed=len(valid) - len(demoted),
        demoted=tuple(demoted),
    )


@dataclass(frozen=True, slots=True)
class Trial:
    """What the pipeline would have **shipped** for one URL on one trial.

    The reduction over candidates mirrors ``pipeline.build`` exactly: lay out
    every candidate, keep the smallest *valid* result.  That is not the same as
    picking the candidate with fewest machines -- proliferation cuts machines
    but forbids direct insertion on the sprayed edges, so fewer machines can lay
    out larger.  Measuring anything else here would measure a product nobody
    ships.
    """

    url_id: str
    strategy: str
    budget_s: float
    trial: int
    outcome: Outcome
    candidate: str
    #: Wall-clock across *all* candidates: what a user actually waits for.
    seconds: float
    metrics: Metrics | None = None
    buildings: int = 0
    detail: str = ""
    #: How many of the candidate frontier laid out validly, and how many were
    #: offered.  A URL can look fully covered while two of its three candidates
    #: are broken, and that matters: the pipeline's whole reason for emitting a
    #: frontier is to have alternatives when one of them will not lay out.
    candidates_valid: int = 0
    candidates_total: int = 0
    #: Sum of candidate CPU times. ``None`` when loaded legacy samples lack it.
    cpu_seconds: float | None = None
    #: Largest candidate process peak RSS. ``None`` for legacy samples.
    peak_rss_mb: float | None = None
    power: bool = False

    @property
    def area(self) -> int | None:
        return self.metrics.area if self.metrics is not None else None


def ship(samples: Sequence[Sample]) -> Trial:
    """Reduce one trial's candidate sweep to the single result that ships."""
    if not samples:
        raise ValueError("ship() needs at least one sample")
    first = samples[0]
    total = sum(s.seconds for s in samples)
    cpu_seconds = (
        sum(s.cpu_seconds for s in samples if s.cpu_seconds is not None)
        if all(s.cpu_seconds is not None for s in samples)
        else None
    )
    peak_rss_mb = (
        max(s.peak_rss_mb for s in samples if s.peak_rss_mb is not None)
        if all(s.peak_rss_mb is not None for s in samples)
        else None
    )
    winners = [s for s in samples if s.outcome is Outcome.VALID and s.metrics is not None]
    if winners:
        best = min(winners, key=lambda s: s.metrics.area if s.metrics else 0)
        return Trial(
            first.url_id,
            first.strategy,
            first.budget_s,
            first.trial,
            Outcome.VALID,
            best.candidate,
            total,
            metrics=best.metrics,
            buildings=best.buildings,
            candidates_valid=len(winners),
            candidates_total=len(samples),
            cpu_seconds=cpu_seconds,
            peak_rss_mb=peak_rss_mb,
            power=first.power,
        )

    by_outcome = {s.outcome: s for s in reversed(samples)}
    for outcome in _SEVERITY:
        if outcome in by_outcome:
            worst = by_outcome[outcome]
            details = sorted({s.detail for s in samples if s.outcome is outcome and s.detail})
            return Trial(
                first.url_id,
                first.strategy,
                first.budget_s,
                first.trial,
                outcome,
                worst.candidate,
                total,
                detail="; ".join(details),
                candidates_valid=0,
                candidates_total=len(samples),
                cpu_seconds=cpu_seconds,
                peak_rss_mb=peak_rss_mb,
                power=first.power,
            )
    raise AssertionError(f"unreachable: no outcome among {[s.outcome for s in samples]}")


@dataclass(frozen=True, slots=True)
class Cell:
    """Every trial for one ``(url, strategy, budget)``.

    The counts are the denominators.  ``median_area`` is ``None`` unless at
    least one trial shipped, and every consumer must handle that -- there is no
    "0" or "inf" placeholder to accidentally average.
    """

    url_id: str
    strategy: str
    budget_s: float
    trials: tuple[Trial, ...] = ()

    @property
    def n(self) -> int:
        return len(self.trials)

    def count(self, outcome: Outcome) -> int:
        return sum(1 for t in self.trials if t.outcome is outcome)

    @property
    def areas(self) -> tuple[int, ...]:
        return tuple(t.area for t in self.trials if t.area is not None)

    @property
    def median_area(self) -> int | None:
        areas = self.areas
        return int(statistics.median(areas)) if areas else None

    @property
    def lo(self) -> int | None:
        return min(self.areas) if self.areas else None

    @property
    def hi(self) -> int | None:
        return max(self.areas) if self.areas else None

    @property
    def relative_spread(self) -> float:
        """``(hi - lo) / median``: the solver's own run-to-run noise on this cell.

        The number that decides whether any A-vs-B gap is real.  If it is 15%
        and the gap is 8%, the gap is the solver shrugging.
        """
        med = self.median_area
        if med is None or med == 0 or self.hi is None or self.lo is None:
            return 0.0
        return (self.hi - self.lo) / med

    @property
    def median_seconds(self) -> float:
        return statistics.median([t.seconds for t in self.trials]) if self.trials else 0.0

    def median_of(self, pick: Callable[[Trial], int]) -> int | None:
        """Median of one composition metric over the shipped trials.

        Area is the headline but not the whole story: building count is how
        unpleasant the blueprint is to paste, and belt tiles versus direct
        inserts is *why* one strategy won -- a belt run replaced by a single
        sorter is denser and cheaper at the same time.
        """
        vals = [pick(t) for t in self.trials if t.metrics is not None]
        return int(statistics.median(vals)) if vals else None

    @property
    def covered(self) -> bool:
        """At least one trial shipped.  The weakest honest coverage claim."""
        return bool(self.areas)

    @property
    def always(self) -> bool:
        """*Every* trial shipped.  A strategy that works 1 run in 5 is not fixed."""
        return self.n > 0 and len(self.areas) == self.n

    @property
    def candidate_health(self) -> str:
        """``k/n candidates`` on the shipped trials, when some of them failed.

        A URL that reads as fully covered can still be one broken candidate away
        from refusing outright, and the report should say so before that happens
        rather than after.
        """
        shipped = [t for t in self.trials if t.outcome is Outcome.VALID]
        if not shipped or all(t.candidates_valid == t.candidates_total for t in shipped):
            return ""
        lo = min(t.candidates_valid for t in shipped)
        total = max(t.candidates_total for t in shipped)
        return f"only {lo}/{total} candidates laid out"

    @property
    def why(self) -> str:
        """One line naming what went wrong, grouped by kind, for the table."""
        parts: list[str] = []
        for outcome in _SEVERITY:
            hits = [t for t in self.trials if t.outcome is outcome]
            if not hits:
                continue
            detail = next((t.detail for t in hits if t.detail), "")
            parts.append(f"{outcome.value} x{len(hits)}" + (f" ({detail[:60]})" if detail else ""))
        return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class Pair:
    """One URL where both strategies were *attempted* at one budget."""

    url_id: str
    budget_s: float
    a: Cell
    b: Cell

    @property
    def comparable(self) -> bool:
        return self.a.median_area is not None and self.b.median_area is not None

    @property
    def ratio(self) -> float | None:
        """``B / A`` of medians.  Below 1 means B is denser."""
        if self.a.median_area is None or self.b.median_area is None or not self.a.median_area:
            return None
        return self.b.median_area / self.a.median_area

    @property
    def bounds(self) -> tuple[float, float] | None:
        """Worst and best B/A across the observed spread of both cells.

        This is the honest interval given nondeterministic CP-SAT: the best case
        for B is its smallest area over A's largest, the worst is the reverse.
        """
        if self.a.lo is None or self.a.hi is None or self.b.lo is None or self.b.hi is None:
            return None
        if not self.a.hi or not self.a.lo:
            return None
        return (self.b.lo / self.a.hi, self.b.hi / self.a.lo)

    @property
    def separated(self) -> bool:
        """Whether the observed spreads keep 1.0 outside the interval.

        A pair that is not separated has no verdict at this sample size,
        regardless of what its medians say.  With ``--repeat 1`` nothing is
        ever separated, which is the correct answer to one sample per cell.
        """
        bounds = self.bounds
        if bounds is None or self.a.n < 2 or self.b.n < 2:
            return False
        lo, hi = bounds
        # A degenerate interval means both strategies were deterministic across
        # every repeat, so the ratio is exact -- including an exact tie, which
        # the deadband then classifies. Requiring hi < 1 here would silently
        # discard the cleanest verdicts in the table.
        if lo == hi:
            return True
        return hi < 1.0 or lo > 1.0


@dataclass(frozen=True, slots=True)
class Comparison:
    """The whole A-vs-B answer at one time budget, denominators attached.

    Constructed only through :func:`compare`, which guarantees ``pairs`` covers
    every attempted URL, so ``n_urls`` is a real denominator rather than a
    hopeful one.
    """

    budget_s: float
    a_name: str
    b_name: str
    pairs: tuple[Pair, ...] = ()
    deadband: float = DENSITY_DEADBAND
    cross: CrossSummary = field(default_factory=lambda: CrossSummary(available=False))

    @property
    def n_urls(self) -> int:
        return len(self.pairs)

    @property
    def a_covered(self) -> int:
        return sum(1 for p in self.pairs if p.a.covered)

    @property
    def b_covered(self) -> int:
        return sum(1 for p in self.pairs if p.b.covered)

    @property
    def a_always(self) -> int:
        return sum(1 for p in self.pairs if p.a.always)

    @property
    def b_always(self) -> int:
        return sum(1 for p in self.pairs if p.b.always)

    @property
    def comparable(self) -> tuple[Pair, ...]:
        return tuple(p for p in self.pairs if p.comparable)

    @property
    def n_pairs(self) -> int:
        return len(self.comparable)

    @property
    def geo_mean(self) -> float | None:
        """Geometric mean of B/A over URLs where **both** shipped.

        ``None`` rather than 1.0 when there is nothing to compare: a neutral
        ratio would read as "they tied", which is a different claim from "no
        comparison was possible".
        """
        ratios = [r for p in self.comparable if (r := p.ratio) is not None]
        return geometric_mean(ratios) if ratios else None

    @property
    def separated(self) -> tuple[Pair, ...]:
        return tuple(p for p in self.comparable if p.separated)

    @property
    def wins(self) -> tuple[int, int, int]:
        """``(a_wins, b_wins, ties)`` over *separated* pairs only.

        A sign count, not a mean: it survives one enormous stress case in a way
        an average of ratios does not, and it is what a sceptic will ask for.
        """
        a = b = tie = 0
        for p in self.separated:
            r = p.ratio
            if r is None:
                continue
            if r < 1.0 - self.deadband:
                b += 1
            elif r > 1.0 + self.deadband:
                a += 1
            else:
                tie += 1
        return a, b, tie

    @property
    def noise_floor(self) -> tuple[float, float]:
        """Median relative spread of each strategy, over cells with >=2 trials.

        Printed next to the effect size so the reader can see whether the effect
        clears the solver's own run-to-run variation.
        """

        def med(cells: list[Cell]) -> float:
            vals = [c.relative_spread for c in cells if c.n >= 2 and c.covered]
            return statistics.median(vals) if vals else 0.0

        return med([p.a for p in self.pairs]), med([p.b for p in self.pairs])

    def headline(self) -> list[str]:
        """The verdict, coverage first, always with denominators.

        Coverage is printed before density and the density line refuses to exist
        without it.  This ordering is the whole point: a strategy that refuses
        half the corpus is not "denser", whatever the median of the other half
        says.
        """
        n = self.n_urls
        lines = [
            f"COVERAGE at budget={self.budget_s:g}s "
            f"(denominator: {n} URL{'s' if n != 1 else ''} attempted)",
            f"  {self.a_name:<10} valid on {self.a_covered}/{n} URLs "
            f"({self.a_always}/{n} on every repeat)",
            f"  {self.b_name:<10} valid on {self.b_covered}/{n} URLs "
            f"({self.b_always}/{n} on every repeat)",
        ]

        if self.a_covered != self.b_covered:
            ahead = self.a_name if self.a_covered > self.b_covered else self.b_name
            lines.append(
                f"  -> {ahead} covers more of the corpus. Coverage outranks "
                f"density: a strategy that cannot lay out a spec has no area to "
                f"compare on it."
            )

        if not self.n_pairs:
            lines.append(
                "DENSITY: no comparison possible -- 0 URLs where both strategies "
                "shipped a valid layout."
            )
            return lines

        geo = self.geo_mean
        assert geo is not None  # n_pairs > 0 implies at least one ratio
        a_wins, b_wins, ties = self.wins
        a_noise, b_noise = self.noise_floor
        pct = abs(1.0 - geo) * 100.0
        who = self.b_name if geo < 1.0 else self.a_name
        plural = "URL" if self.n_pairs == 1 else "URLs"
        lines += [
            f"DENSITY (paired, denominator: {self.n_pairs}/{n} URLs where BOTH shipped)",
            f"  geometric mean B/A = {geo:.3f}  -> {who} is {pct:.1f}% denser "
            f"over {'that' if self.n_pairs == 1 else 'those'} {self.n_pairs} {plural}",
            f"  separated from run-to-run noise on {len(self.separated)}/{self.n_pairs} "
            f"of them: {self.a_name} {a_wins}, {self.b_name} {b_wins}, tie {ties}",
            f"  solver noise floor (median spread/median area): "
            f"{self.a_name} {a_noise * 100:.1f}%, {self.b_name} {b_noise * 100:.1f}%",
        ]
        if not self.separated:
            # Printing a ratio nothing supports is how the last wrong answer got
            # quoted, so the line that says it is unsupported has to be as loud
            # as the ratio itself.
            lines.append(
                "  -> NOTHING is separated from noise at this sample size. The "
                "ratio above has no support; raise --repeat before quoting it."
            )
        if pct <= max(a_noise, b_noise) * 100.0:
            lines.append(
                "  -> the effect does NOT clear the solver's own run-to-run "
                "variation. Treat it as no difference."
            )
        if self.n_pairs < n:
            lines.append(
                f"  -> this ratio describes {self.n_pairs} of {n} URLs only. It is "
                f"not a corpus-wide claim, and the {n - self.n_pairs} unpaired "
                f"URL(s) are not evidence for either side."
            )
        return lines


def compare(
    trials: Sequence[Trial],
    *,
    a_name: str,
    b_name: str,
    budget_s: float,
    url_ids: Sequence[str],
    cross: CrossSummary | None = None,
) -> Comparison:
    """Build the comparison at one budget.

    ``url_ids`` is passed explicitly rather than derived from ``trials`` so a
    URL that produced no trials at all -- a spec that would not even resolve --
    still appears in the denominator.  Deriving it would make a broken URL look
    like a URL nobody ran, which flatters both strategies equally and is still
    wrong.
    """
    buckets: dict[tuple[str, str], list[Trial]] = {}
    for t in trials:
        if t.budget_s != budget_s:
            continue
        buckets.setdefault((t.url_id, t.strategy), []).append(t)

    pairs = tuple(
        Pair(
            url_id=u,
            budget_s=budget_s,
            a=Cell(u, a_name, budget_s, tuple(buckets.get((u, a_name), []))),
            b=Cell(u, b_name, budget_s, tuple(buckets.get((u, b_name), []))),
        )
        for u in url_ids
    )
    return Comparison(
        budget_s=budget_s,
        a_name=a_name,
        b_name=b_name,
        pairs=pairs,
        cross=cross if cross is not None else CrossSummary(available=False),
    )


def trials_from(samples: Sequence[Sample]) -> list[Trial]:
    """Group samples by ``(url, strategy, budget, trial, power)`` and ship."""
    groups: dict[tuple[str, str, float, int, bool], list[Sample]] = {}
    for sample in samples:
        key = (
            sample.url_id,
            sample.strategy,
            sample.budget_s,
            sample.trial,
            sample.power,
        )
        groups.setdefault(key, []).append(sample)
    return [ship(group) for group in groups.values()]


def _belts(t: Trial) -> int:
    return t.metrics.belt_tiles if t.metrics is not None else 0


def _direct(t: Trial) -> int:
    return t.metrics.direct_inserts if t.metrics is not None else 0


def _buildings(t: Trial) -> int:
    return t.buildings


def _cell_area(cell: Cell) -> str:
    med = cell.median_area
    if med is None:
        return "-"
    if cell.n < 2 or cell.lo == cell.hi:
        return str(med)
    return f"{med} [{cell.lo}-{cell.hi}]"


def _num(value: int | None) -> str:
    return "-" if value is None else str(value)


def render_text(comparison: Comparison) -> list[str]:
    """The per-budget table: coverage, then density, then composition."""
    lines = list(comparison.headline())
    lines.append("")

    head = (
        f"{'spec':<24}{comparison.a_name + ' area':>18}{'ok':>6}"
        f"{comparison.b_name + ' area':>18}{'ok':>6}{'B/A':>8}{'sep':>5}"
        f"{'A s':>7}{'B s':>7}"
    )
    lines += [head, "-" * len(head)]
    for p in comparison.pairs:
        ratio = p.ratio
        lines.append(
            f"{p.url_id[:23]:<24}{_cell_area(p.a):>18}"
            f"{f'{len(p.a.areas)}/{p.a.n}':>6}"
            f"{_cell_area(p.b):>18}"
            f"{f'{len(p.b.areas)}/{p.b.n}':>6}"
            f"{(f'{ratio:.2f}x' if ratio is not None else '-'):>8}"
            f"{('yes' if p.separated else 'no' if p.comparable else '-'):>5}"
            f"{p.a.median_seconds:>6.1f}s{p.b.median_seconds:>6.1f}s"
        )
        # Name the failure kind on its own line. REFUSED, INVALID, ERROR and
        # CROSSFAIL are four different bugs; a shared blank cell would hide
        # which one is actually biting.
        for cell in (p.a, p.b):
            note = cell.why if not cell.always else ""
            health = cell.candidate_health
            if health:
                note = f"{note}; {health}" if note else health
            if note:
                lines.append(f"    {cell.strategy}: {note}")

    paired = comparison.comparable
    if paired:
        lines += ["", "Composition on the paired URLs (median over repeats):"]
        chead = (
            f"{'spec':<24}{'A blds':>9}{'B blds':>9}{'A belt':>9}{'B belt':>9}"
            f"{'A d.ins':>9}{'B d.ins':>9}"
        )
        lines += [chead, "-" * len(chead)]
        for p in paired:
            lines.append(
                f"{p.url_id[:23]:<24}"
                f"{_num(p.a.median_of(_buildings)):>9}{_num(p.b.median_of(_buildings)):>9}"
                f"{_num(p.a.median_of(_belts)):>9}{_num(p.b.median_of(_belts)):>9}"
                f"{_num(p.a.median_of(_direct)):>9}{_num(p.b.median_of(_direct)):>9}"
            )
    return lines


def budget_flip(comparisons: Sequence[Comparison]) -> str:
    """Whether the winner changes across the swept budgets.

    Time budget is a confound with teeth: a strategy that uses its budget better
    looks denser at 2s and worse at 10s.  If the sign flips, the honest headline
    is "it depends on the budget", not either strategy's name.
    """
    signs: list[tuple[float, str]] = []
    for c in comparisons:
        geo = c.geo_mean
        if geo is None or c.n_pairs == 0:
            continue
        if abs(1.0 - geo) <= c.deadband:
            signs.append((c.budget_s, "tie"))
        else:
            signs.append((c.budget_s, c.b_name if geo < 1.0 else c.a_name))
    if len(signs) < 2:
        return ""
    winners = {w for _, w in signs}
    if len(winners) == 1:
        return f"Winner is stable across budgets {[f'{b:g}s' for b, _ in signs]}: {signs[0][1]}."
    return (
        "WINNER FLIPS WITH TIME BUDGET: "
        + ", ".join(f"{b:g}s -> {w}" for b, w in signs)
        + ". The budget is not a nuisance parameter here; it decides the answer, "
        "so no single-budget number is the result."
    )


@dataclass(frozen=True, slots=True)
class RunMeta:
    """Everything about a run that a sceptic needs in order to re-run it."""

    tiers: tuple[str, ...]
    budgets: tuple[float, ...]
    repeat: int
    candidates: int
    power: bool
    urls: int
    started: str = ""
    seconds: float = 0.0
    a_name: str = "sequence-pair"
    b_name: str = "freeform"

    def lines(self) -> list[str]:
        return [
            f"tiers={'+'.join(self.tiers)}  budgets={[f'{b:g}s' for b in self.budgets]}  "
            f"repeat={self.repeat}  candidates={self.candidates}  "
            f"power={'on' if self.power else 'off'}  urls={self.urls}",
            "CP-SAT runs multi-worker (the shipping default), so it is "
            "nondeterministic by design; repeats measure that, they do not remove it.",
        ]


def render_markdown(comparisons: Sequence[Comparison], meta: RunMeta, cross: CrossSummary) -> str:
    """The generated results section, for pasting into a docs report."""
    out = ["# A/B density comparison (generated)", ""]
    out += [f"- {line}" for line in meta.lines()]
    out += [f"- {cross.summary()}", ""]
    if cross.demoted:
        out += ["Blueprints demoted by cross-validation:", ""]
        out += [f"- `{d}`" for d in cross.demoted]
        out.append("")

    flip = budget_flip(comparisons)
    if flip:
        out += [f"**{flip}**", ""]

    for c in comparisons:
        out += [f"## budget = {c.budget_s:g}s", "", "```"]
        out += render_text(c)
        out += ["```", ""]
    out += [
        "## How to read this",
        "",
        "Coverage is stated before density and the density ratio names its own",
        "denominator, because an area ratio over the subset where both strategies",
        "happened to succeed is not a corpus-wide claim. Only placements the",
        "validator accepted contribute an area: invalid layouts are systematically",
        "smaller, since an unrouted net is a belt run that does not exist, so",
        "scoring them rewards dropping connections rather than packing well.",
        "",
    ]
    return "\n".join(out)


def to_json(samples: Sequence[Sample], meta: RunMeta, cross: CrossSummary) -> dict[str, object]:
    """Machine-readable dump.  Blueprints are omitted -- they are large and the
    verdict must not depend on re-reading them."""
    return {
        "meta": {
            "tiers": list(meta.tiers),
            "budgets": list(meta.budgets),
            "repeat": meta.repeat,
            "candidates": meta.candidates,
            "power": meta.power,
            "urls": meta.urls,
            "started": meta.started,
            "seconds": meta.seconds,
            "a": meta.a_name,
            "b": meta.b_name,
        },
        "crossvalidation": {
            "available": cross.available,
            "complete": cross.complete,
            "checked": cross.checked,
            "passed": cross.passed,
            "demoted": list(cross.demoted),
            "reason": cross.reason,
        },
        "samples": [
            {
                "url_id": s.url_id,
                "candidate": s.candidate,
                "strategy": s.strategy,
                "budget_s": s.budget_s,
                "trial": s.trial,
                "outcome": s.outcome.value,
                "power": s.power,
                "seconds": round(s.seconds, 3),
                "cpu_seconds": round(s.cpu_seconds, 6) if s.cpu_seconds is not None else None,
                "peak_rss_mb": round(s.peak_rss_mb, 3) if s.peak_rss_mb is not None else None,
                "area": s.area,
                "used_tiles": s.metrics.used_tiles if s.metrics else None,
                "buildings": s.buildings or None,
                "belt_tiles": s.metrics.belt_tiles if s.metrics else None,
                "direct_inserts": s.metrics.direct_inserts if s.metrics else None,
                "machines": s.metrics.machines if s.metrics else None,
                "detail": s.detail,
            }
            for s in samples
        ],
    }


def _number(row: Mapping[str, object], key: str, *, required: bool = True) -> float | None:
    value = row.get(key)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"sample {key!r} must be numeric")
    return float(value)


def _required_string(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"sample {key!r} must be a nonempty string")
    return value


def _required_number(row: Mapping[str, object], key: str) -> float:
    value = _number(row, key)
    if value is None:  # ``required=True`` makes this defensive, and narrows the type.
        raise ValueError(f"sample {key!r} must be numeric")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a non-negative integer")
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"{label} must be a non-negative integer")
        number = int(value)
    else:
        number = value
    if number < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return number


_MISSING = object()


def _integer(
    row: Mapping[str, object],
    key: str,
    default: object = _MISSING,
) -> int:
    value = row.get(key, default)
    if value is _MISSING:
        raise ValueError(f"sample {key!r} must be a non-negative integer")
    return _nonnegative_integer(value, f"sample {key!r}")


def cross_summary_from_json(document: Mapping[str, object]) -> CrossSummary:
    """Parse independent decoder evidence without treating absence as success."""
    raw = document.get("crossvalidation")
    if raw is None:
        return CrossSummary(available=False, reason="cross-validation evidence missing")
    if not isinstance(raw, dict):
        raise ValueError("result JSON crossvalidation must be an object")
    available = raw.get("available")
    if type(available) is not bool:
        raise ValueError("cross-validation 'available' must be a boolean")
    complete = raw.get("complete", True)
    if type(complete) is not bool:
        raise ValueError("cross-validation 'complete' must be a boolean")
    demoted = raw.get("demoted", [])
    if not isinstance(demoted, list) or any(
        not isinstance(item, str) or not item for item in demoted
    ):
        raise ValueError("cross-validation 'demoted' must be a list of non-empty strings")
    reason = raw.get("reason", "")
    if not isinstance(reason, str):
        raise ValueError("cross-validation 'reason' must be a string")
    return CrossSummary(
        available=available,
        complete=complete,
        checked=_nonnegative_integer(
            raw.get("checked", 0),
            "cross-validation 'checked'",
        ),
        passed=_nonnegative_integer(
            raw.get("passed", 0),
            "cross-validation 'passed'",
        ),
        demoted=tuple(demoted),
        reason=reason,
    )


def _parsed_buildings(row: Mapping[str, object], outcome: Outcome) -> int:
    if row.get("buildings") is None:
        if outcome is Outcome.VALID:
            raise ValueError("sample 'buildings' must be numeric")
        return 0
    return _integer(row, "buildings")


def _boolean(row: Mapping[str, object], key: str, default: bool) -> bool:
    value = row.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"sample {key!r} must be a boolean")
    return value


def samples_from_json(document: Mapping[str, object]) -> list[Sample]:
    """Parse persisted samples, accepting documents written before CPU/RSS metrics."""
    raw_samples = document.get("samples")
    if not isinstance(raw_samples, list):
        raise ValueError("result JSON must contain a samples list")
    raw_meta = document.get("meta", {})
    if not isinstance(raw_meta, dict):
        raise ValueError("result JSON meta must be an object")
    meta_power = _boolean(raw_meta, "power", False)
    samples: list[Sample] = []
    for raw in raw_samples:
        if not isinstance(raw, dict):
            raise ValueError("every persisted sample must be an object")
        row: Mapping[str, object] = raw
        try:
            outcome = Outcome(str(row["outcome"]))
            raw_area = row.get("area")
            area = None if raw_area is None else _nonnegative_integer(raw_area, "sample 'area'")
            metrics = None
            if outcome is Outcome.VALID:
                if area is None:
                    raise ValueError("a persisted VALID sample must carry area")
                metrics = Metrics(
                    area=area,
                    used_tiles=_integer(row, "used_tiles"),
                    width=_integer(row, "width", area),
                    height=_integer(row, "height", 1),
                    machines=_integer(row, "machines"),
                    belt_tiles=_integer(row, "belt_tiles"),
                    sorters=_integer(row, "sorters", 0),
                    direct_inserts=_integer(row, "direct_inserts"),
                    towers=_integer(row, "towers", 0),
                    altitude_levels=_integer(row, "altitude_levels", 1),
                )
            samples.append(
                Sample(
                    url_id=_required_string(row, "url_id"),
                    candidate=_required_string(row, "candidate"),
                    strategy=_required_string(row, "strategy"),
                    budget_s=_required_number(row, "budget_s"),
                    trial=_integer(row, "trial"),
                    outcome=outcome,
                    seconds=_required_number(row, "seconds"),
                    metrics=metrics,
                    buildings=_parsed_buildings(row, outcome),
                    detail=str(row.get("detail", "")),
                    cpu_seconds=_number(row, "cpu_seconds", required=False),
                    peak_rss_mb=_number(row, "peak_rss_mb", required=False),
                    power=_boolean(row, "power", meta_power),
                )
            )
        except KeyError as exc:
            raise ValueError(f"persisted sample lacks {exc.args[0]!r}") from exc
    return samples
