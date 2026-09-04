"""Adaptive large-neighbourhood operator selection for the placement search.

The measured finding this module is built around is a negative one, recorded in
full at ``freeform._pack``'s removed routing-capacity cut: no cheap surrogate
predicts whether a placement will route (four estimates, 270 real packs, AUC
0.500 / 0.500 / 0.535 / 0.525, with cut-capacity slack anti-correlated at 0.422
as the control).  So an operator here is never scored by a proxy at selection
time.  It is paid, one evaluation later, by what the real detailed router then
did -- which is why :meth:`OperatorSession.observe_and_select` credits the
previous choice before it makes the next one.

Nothing in selection reads a clock.  ``reward_vector`` has no time divisor and
consults no RNG, so for a fixed seed and a fixed deterministic budget the
sequence of choices replays exactly.  ``routing_seconds`` is carried on the
outcome and summed for telemetry, and is read nowhere else.

The two ledgers are otherwise phi-isomorphic -- `observe` credits both from one
reward vector and one `applied` flag -- so with `probe_product` on, `select`
walks the destroy x repair product on its first `|D| x |R|` draws.  Without
that walk, half the shipped pairings are unreachable under every reward
sequence (R3 section 1.2).  `probe_product` defaults OFF (Ruling E11): it cost
a clean cell its wall at budget 30 (task-9-diagnosis.md), so production ships
master's own pairing and the probe is exercised by tests only.

The shipped portfolio is deliberately four operators.  The other enum members
exist so adding one later is a new dispatch branch rather than a redesign; the
rule for adding one is that a refusing corpus cell names its mechanism.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    FeedbackState,
    select_lns_neighbourhood,
)
from flab2bp.layout.sequence_pair import (
    DecodedPlacement,
    GapProfile,
    PlacementProblem,
    SequencePair,
)

#: Per-observation discount applied to EVERY arm's count and reward sums, which
#: is what makes this a discounted UCB rather than a stationary one: an operator
#: that helped ten stages ago should not outvote what the router said last.
C_DUCB_DISCOUNT = 0.9
#: Coefficient of the SINGLE exploration bonus, appended after the five means as
#: the last tie-break.  A bonus added to every rank would let exploration on
#: rank 4 outvote a real difference on rank 1, which is the exchange a
#: lexicographic reward exists to forbid.
C_DUCB_EXPLORATION = 0.5
#: Means are quantized before comparison so float association order cannot
#: decide an arm.  Ties then fall to declaration order.
C_DUCB_SCORE_QUANTUM = 1e-9
#: Buckets for ``OperatorContext.remaining_fraction``.
C_CONTEXT_FRACTION_STEPS = 10
#: Bucket below which LOCAL_EXACT_PACK is not offered: a window started with no
#: room to finish spends its whole cost and buys nothing.
C_WINDOW_FRACTION_FLOOR = 1
#: Destroy-cardinality bounds and the schedule between them.
C_MIN_DESTROY_STRIPS = 2
C_MAX_DESTROY_STRIPS = 12
C_SCALE_FRACTION = 0.15
C_SCALE_GROWTH = 2
#: `select_lns_neighbourhood`'s ring-growth threshold.  Production has never
#: passed a non-zero stagnation, so the branch stays dormant; the constant is
#: here so the call site is explicit rather than relying on a default.
C_GROW_AFTER = 2
#: Reward ranks, in lexicographic order.  See :func:`reward_vector`.
REWARD_RANKS = 5


class DestroyOperator(StrEnum):
    """Which strips a repair may move.  Declaration order is the tie-break."""

    FAILED_ENDPOINTS = "failed-endpoints"
    BAND_BOUNDARY = "band-boundary"
    #: Follow-ups: named so the enum is extensible, with no dispatch branch and
    #: no arm.  Added when a refusing cell names the mechanism.
    BLOCKER_COMPONENT = "blocker-component"
    CONGESTED_CUT = "congested-cut"
    RELATED_CARGO = "related-cargo"
    DIVERSIFY = "diversify"


class RepairOperator(StrEnum):
    """How destroyed strips are put back.  Declaration order is the tie-break."""

    SEQUENCE_REINSERT = "sequence-reinsert"
    LOCAL_EXACT_PACK = "local-exact-pack"
    #: Follow-up, as above.
    ROUTING_REGRET = "routing-regret"


SHIPPED_DESTROY: tuple[DestroyOperator, ...] = (
    DestroyOperator.FAILED_ENDPOINTS,
    DestroyOperator.BAND_BOUNDARY,
)
SHIPPED_REPAIR: tuple[RepairOperator, ...] = (
    RepairOperator.SEQUENCE_REINSERT,
    RepairOperator.LOCAL_EXACT_PACK,
)


@dataclass(frozen=True, slots=True)
class OperatorContext:
    """The situation the selector chooses in.  Every field has a reader."""

    #: Read by :func:`operator_scale`.
    strip_count: int
    #: Read by :func:`operator_scale`.
    stagnation: int
    #: Read by :meth:`OperatorSession.select` to gate LOCAL_EXACT_PACK.
    remaining_fraction: int

    def __post_init__(self) -> None:
        for value, name in (
            (self.strip_count, "strip count"),
            (self.stagnation, "stagnation"),
            (self.remaining_fraction, "remaining fraction"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"operator context {name} must be a non-negative integer")
        if self.remaining_fraction > C_CONTEXT_FRACTION_STEPS:
            raise ValueError("remaining fraction must be a bucket index")


@dataclass(frozen=True, slots=True)
class OperatorChoice:
    """One destroy/repair pairing at one cardinality, with its selection index."""

    destroy: DestroyOperator
    repair: RepairOperator
    scale: int
    ordinal: int

    def __post_init__(self) -> None:
        if type(self.scale) is not int or self.scale < 1:
            raise ValueError("operator scale must be a positive integer")
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("operator ordinal must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class OperatorMetrics:
    """The five measured quantities the reward ranks over, in rank order."""

    validator_clean: bool
    failed_nets: int
    band_overflow: int
    congestion: float
    #: The REALIZED extent, ``width * used_height``.  The outline height is a
    #: search parameter; the extent is what gets built and validated.
    area: int

    def __post_init__(self) -> None:
        if type(self.validator_clean) is not bool:
            raise ValueError("validator-clean marker must be a bool")
        for value, name in (
            (self.failed_nets, "failed nets"),
            (self.band_overflow, "band overflow"),
            (self.area, "area"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"operator metric {name} must be a non-negative integer")
        if not math.isfinite(self.congestion) or self.congestion < 0.0:
            raise ValueError("operator metric congestion must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class OperatorOutcome:
    """One choice, the evaluation before it, and the evaluation after it.

    No measured seconds live here.  A wall-clock divisor would make the ledger a
    function of machine load, and the corpus audit runs sixteen cells in parallel
    by design -- so rather than carry a field nothing reads (and invite someone
    to read it), seconds go straight to :meth:`OperatorSession.observe`, which
    sums them for telemetry.
    """

    choice: OperatorChoice
    before: OperatorMetrics
    after: OperatorMetrics
    applied: bool

    def __post_init__(self) -> None:
        if type(self.applied) is not bool:
            raise ValueError("outcome applied marker must be a bool")


def reward_vector(outcome: OperatorOutcome) -> tuple[float, ...]:
    """Return one lexicographic reward vector.  No divisor, no clock.

    The ordering is the reliability design's: a validator-clean placement, then
    fewer failed nets, then less projection/band overflow, then less congestion,
    then a smaller area.  Area is credited only when the placement is clean, so
    no amount of density can buy back validity -- that is the whole reason the
    reward is a vector rather than a weighted sum.
    """
    before, after = outcome.before, outcome.after
    clean = 1.0 if after.validator_clean and not before.validator_clean else 0.0
    failed = float(max(0, before.failed_nets - after.failed_nets))
    overflow = float(max(0, before.band_overflow - after.band_overflow))
    congestion = max(0.0, before.congestion - after.congestion)
    area = (
        max(0, before.area - after.area) / before.area
        if after.validator_clean and before.area > 0
        else 0.0
    )
    return (clean, failed, overflow, congestion, area)


def remaining_fraction_bucket(remaining_s: float, ceiling_s: float) -> int:
    """Quantize a real clock ratio so wall jitter cannot flip a decision."""
    if ceiling_s <= 0.0:
        return 0
    ratio = min(1.0, max(0.0, remaining_s / ceiling_s))
    return int(ratio * C_CONTEXT_FRACTION_STEPS)


def operator_scale(context: OperatorContext) -> int:
    """Return the destroy cardinality for one situation.

    Scale is a function of the context and not a learned arm: folding
    cardinalities into the arm identity would multiply an arm count that already
    has only two to eight observations per budget to learn from on the largest
    cells.
    """
    base = max(C_MIN_DESTROY_STRIPS, round(C_SCALE_FRACTION * context.strip_count))
    grown = base + C_SCALE_GROWTH * context.stagnation
    return max(1, min(grown, C_MAX_DESTROY_STRIPS, max(1, context.strip_count - 1)))


def metrics_from_evaluation(
    result: DetailedRouteResult,
    decoded: DecodedPlacement,
    feedback: FeedbackState,
    *,
    outline_height: int,
    band_target_width: int,
    validator_clean: bool,
) -> OperatorMetrics:
    """Read the five reward quantities off one completed evaluation.

    ``congestion`` is the summed cell history over the failure walls, which is
    the same evidence `_pack`'s feedback terms and the annealing `history_cost`
    already consume; it is the only rank whose scale is spec-dependent, which is
    why every rank is compared as an improvement rather than as a level.
    """
    congestion = 0.0
    for failure in result.failures:
        for cell in failure.wall:
            congestion += feedback.cell_history.get(cell, 0.0)
    overflow = max(0, decoded.used_height - outline_height) + max(
        0, decoded.width - band_target_width
    )
    return OperatorMetrics(
        validator_clean=validator_clean,
        failed_nets=result.failed_count,
        band_overflow=overflow,
        congestion=congestion,
        area=decoded.width * decoded.used_height,
    )


def _capped(strips: Iterable[int], *, scale: int) -> frozenset[int]:
    """Truncate a destroy set in the order its operator ranked it.

    Order-preserving on purpose.  `FAILED_ENDPOINTS` hands over an unordered set
    and sorts it itself, so index order is its ranking; `BAND_BOUNDARY` ranks by
    overflow contribution, and truncating THAT by index would drop the worst
    offender and keep the mildest, which is the opposite of the operator.
    """
    return frozenset(list(strips)[:scale])


def _band_boundary(
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    *,
    band_target_width: int,
) -> list[int]:
    """Strips ranked by how much they push the extent past what a band accepts.

    This is the operator the "fits no latitude band" refusals name: the failure
    is that the finished extent has no legal frame, and the strips that own the
    extent are exactly the ones whose right edge reaches beyond the target.

    A RANKED list, not a set, because `_capped` truncates in the order it is
    given: the worst offender must survive a small `scale`, and index order
    would keep the mildest instead.  Ties on the edge fall to index order so the
    result is deterministic.
    """
    if band_target_width >= decoded.width and decoded.used_height <= problem.outline_height:
        return []
    ranked = sorted(
        range(problem.size),
        key=lambda strip: (
            -(decoded.x[strip] + problem.sizes[strip][0]),
            strip,
        ),
    )
    over = [
        strip
        for strip in ranked
        if decoded.x[strip] + problem.sizes[strip][0] > band_target_width
    ]
    # Nothing over the width but the outline still overflows: the extent problem
    # is vertical, and the widest strips are still the ones with room to move.
    return over or ranked


def destroy_strips(
    operator: DestroyOperator,
    *,
    scale: int,
    result: DetailedRouteResult,
    pair: SequencePair,
    gaps: GapProfile,
    problem: PlacementProblem,
    decoded: DecodedPlacement,
    band_target_width: int,
) -> frozenset[int]:
    """Return the strips one destroy operator frees, capped at ``scale``.

    An operator whose evidence is absent returns an empty set; the caller
    credits that as an unapplied choice rather than retrying it forever.

    ``scale`` is validated here and not only on :class:`OperatorChoice` because
    a zero or negative cap would silently return an empty (or, for a negative
    value, a reversed-slice) destroy set, which reads downstream as "this
    operator had no evidence" -- a wrong answer rather than a refusal.
    """
    if type(scale) is not int or scale < 1:
        raise ValueError("destroy scale must be a positive integer")
    if operator is DestroyOperator.FAILED_ENDPOINTS:
        return _capped(
            sorted(
                select_lns_neighbourhood(
                    result,
                    pair,
                    gaps,
                    problem,
                    decoded,
                    stagnation=0,
                    grow_after=C_GROW_AFTER,
                )
            ),
            scale=scale,
        )
    if operator is DestroyOperator.BAND_BOUNDARY:
        return _capped(
            _band_boundary(problem, decoded, band_target_width=band_target_width),
            scale=scale,
        )
    raise NotImplementedError(
        f"destroy operator {operator.value} is a follow-up with no dispatch branch"
    )


@dataclass(slots=True)
class _Ledger:
    """One discounted count and one discounted reward sum per rank, per arm."""

    counts: dict[str, float]
    rewards: dict[str, list[float]]
    order: tuple[str, ...]

    @classmethod
    def over(cls, arms: Sequence[str]) -> _Ledger:
        return cls(
            counts=dict.fromkeys(arms, 0.0),
            rewards={arm: [0.0] * REWARD_RANKS for arm in arms},
            order=tuple(arms),
        )

    def decay(self, discount: float) -> None:
        for arm in self.order:
            self.counts[arm] *= discount
            rewards = self.rewards[arm]
            for rank in range(REWARD_RANKS):
                rewards[rank] *= discount

    def credit(self, arm: str, reward: Sequence[float]) -> None:
        self.counts[arm] += 1.0
        rewards = self.rewards[arm]
        for rank in range(REWARD_RANKS):
            rewards[rank] += float(reward[rank])

    def best(self, exploration: float, *, among: Sequence[str] | None = None) -> str:
        """Return the winning arm: five means lexicographically, then one bonus."""
        arms = tuple(among) if among else self.order
        untried = [arm for arm in arms if self.counts[arm] == 0.0]
        if untried:
            return untried[0]
        total = sum(self.counts[arm] for arm in self.order)
        logarithm = math.log(max(total, math.e))
        best_arm = arms[0]
        best_score: tuple[float, ...] | None = None
        for arm in arms:
            count = self.counts[arm]
            means = tuple(
                round((self.rewards[arm][rank] / count) / C_DUCB_SCORE_QUANTUM)
                * C_DUCB_SCORE_QUANTUM
                for rank in range(REWARD_RANKS)
            )
            score = (*means, exploration * math.sqrt(logarithm / count))
            if best_score is None or score > best_score:
                best_arm, best_score = arm, score
        return best_arm


class OperatorSession:
    """Deterministic discounted-UCB selection over destroy and repair arms.

    Two independent ledgers rather than one over pairs: the product of the two
    portfolios cannot be learned inside a thirty-second budget, and destroy
    quality and repair quality are separately attributable because both are
    credited by the same realized outcome.
    """

    def __init__(
        self,
        *,
        destroy_arms: Sequence[DestroyOperator] = SHIPPED_DESTROY,
        repair_arms: Sequence[RepairOperator] = SHIPPED_REPAIR,
        discount: float = C_DUCB_DISCOUNT,
        exploration: float = C_DUCB_EXPLORATION,
        probe_product: bool = False,
    ) -> None:
        if not 0.0 < discount <= 1.0:
            raise ValueError("discount must lie in (0, 1]")
        if exploration < 0.0:
            raise ValueError("exploration coefficient must be non-negative")
        destroy = tuple(destroy_arms)
        repair = tuple(repair_arms)
        if not destroy or not repair:
            raise ValueError("an operator session needs at least one arm of each kind")
        if len(set(destroy)) != len(destroy) or len(set(repair)) != len(repair):
            raise ValueError("operator arms must be distinct")
        self._discount = discount
        self._exploration = exploration
        self._probe_product = probe_product
        self._destroy = _Ledger.over([operator.value for operator in destroy])
        self._repair = _Ledger.over([operator.value for operator in repair])
        self._repair_arms = repair
        self._choices: list[OperatorChoice] = []
        self._pending: OperatorChoice | None = None
        self._baseline: OperatorMetrics | None = None
        self._applied = 0
        self._routing_seconds = 0.0

    @property
    def choices(self) -> tuple[OperatorChoice, ...]:
        """Every choice this session has made, in order."""
        return tuple(self._choices)

    @property
    def pending(self) -> OperatorChoice | None:
        """The choice awaiting an outcome, if any."""
        return self._pending

    @property
    def applied(self) -> int:
        """How many observed choices actually ran a destroy and a repair."""
        return self._applied

    @property
    def routing_seconds(self) -> float:
        """Summed measured routing seconds across observations.  Telemetry only."""
        return self._routing_seconds

    @property
    def credit(self) -> Mapping[str, float]:
        """Flat discounted ledger, for telemetry and tests."""
        flat: dict[str, float] = {}
        for ledger in (self._destroy, self._repair):
            for arm in ledger.order:
                flat[f"count:{arm}"] = ledger.counts[arm]
                for rank in range(REWARD_RANKS):
                    flat[f"reward:{arm}:{rank}"] = ledger.rewards[arm][rank]
        return flat

    def _affordable_repairs(self, context: OperatorContext) -> tuple[str, ...]:
        if context.remaining_fraction >= C_WINDOW_FRACTION_FLOOR:
            return self._repair.order
        affordable = tuple(
            operator.value
            for operator in self._repair_arms
            if operator is not RepairOperator.LOCAL_EXACT_PACK
        )
        return affordable or self._repair.order

    def select(self, context: OperatorContext) -> OperatorChoice:
        """Choose the next destroy/repair pairing.  Consults no RNG, no clock.

        WITH ``probe_product`` ON, THE FIRST ``|D| x |R|`` DRAWS WALK THE
        PRODUCT, and the rest is the discounted UCB exactly as before.  Two
        independent ledgers whose untried probes both return `untried[0]` are
        index-ISOMORPHIC forever: `observe` credits both from the same reward
        vector and the same ``applied`` flag, so `best` returns the same INDEX
        in each at every draw and half the advertised portfolio is unreachable
        under every reward sequence.  R3 §1.2 proves it by induction and §1.3
        confirms it over 60,000 randomized draws and 166 real corpus
        selections: zero cross pairings.

        A constant probe OFFSET does not fix it -- a shifted bijection is still a
        bijection, and it only rotates WHICH two pairings are reachable (R3 §5,
        measured).  Walking the product does, and after the walk the two ledgers
        carry genuinely different count and reward patterns, so all four pairings
        stay reachable under the D-UCB.

        THE WALK IS DESTROY-MAJOR IN DECLARATION ORDER, so draw 0 is master's own
        ``(FAILED_ENDPOINTS, SEQUENCE_REINSERT)`` and draw 1 is
        ``(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)`` -- the window posed against the
        routing-failure set, the evidence it was designed for.  Keeping draw 0
        identical is deliberate: it is what the production solver's first repair
        already was, and reversing the repair axis to reach the window one draw
        sooner was measured to move six solver-behaviour tests for no gain.

        ``probe_product`` DEFAULTS TO OFF (Ruling E11): measured
        (``task-9-diagnosis.md``), with the probe on, sequence-pair
        universe-matrix/output-products refused in 3 of 3 runs at budget 30 and
        needed about 54 s at budget 60 against 25 s under master's own pairing,
        because the window's accepted repair on draw 1 sends the search down a
        slower path.  Under master's pairing the window is only ever drawn
        against BAND_BOUNDARY, whose destroy set is always empty or the whole
        problem, so it never actually reaches CP-SAT -- and probe draw 3,
        ``(BAND_BOUNDARY, LOCAL_EXACT_PACK)``, was measured always dropped for
        the same reason (review M1).  The production factory and freeform's
        session both construct with the default, so the shipped behaviour is
        master's pairing; the probe ships for the tests and future measurement.

        TWO LEDGERS ARE KEPT regardless.  The product is PROBED, not LEARNED, so
        this class's reason for not learning the product still holds.

        The probe is a pure function of ``len(self._choices)`` and the two arm
        tuples: no RNG, no clock, no reward.  Replay is preserved; the VALUES of
        the replayed sequence change once, deliberately and gated.

        ``_affordable_repairs`` still governs.  A probe that would name
        LOCAL_EXACT_PACK below ``C_WINDOW_FRACTION_FLOOR`` falls through to the
        D-UCB for both arms rather than smuggling a window past the floor; the
        ordinal still advances, so that pairing loses its probe turn.
        """
        affordable = self._affordable_repairs(context)
        destroy_order = self._destroy.order
        repair_order = self._repair.order
        probe = len(self._choices)
        pairing: tuple[str, str] | None = None
        if self._probe_product and probe < len(destroy_order) * len(repair_order):
            probed_destroy = destroy_order[probe // len(repair_order)]
            probed_repair = repair_order[probe % len(repair_order)]
            if probed_repair in affordable:
                pairing = (probed_destroy, probed_repair)
        if pairing is None:
            pairing = (
                self._destroy.best(self._exploration),
                self._repair.best(self._exploration, among=affordable),
            )
        choice = OperatorChoice(
            destroy=DestroyOperator(pairing[0]),
            repair=RepairOperator(pairing[1]),
            scale=operator_scale(context),
            ordinal=len(self._choices),
        )
        self._choices.append(choice)
        self._pending = choice
        return choice

    def observe(
        self,
        choice: OperatorChoice,
        reward: Sequence[float],
        *,
        applied: bool,
        routing_seconds: float = 0.0,
    ) -> None:
        """Credit one choice with its realized reward vector.

        An unapplied choice still costs a count and earns nothing, so an
        operator whose evidence is chronically absent loses its turn instead of
        being retried forever.
        """
        if len(reward) != REWARD_RANKS:
            raise ValueError(f"reward vector must carry {REWARD_RANKS} ranks")
        if any(not math.isfinite(value) or value < 0.0 for value in reward):
            raise ValueError("reward components must be finite and non-negative")
        credited = tuple(reward) if applied else (0.0,) * REWARD_RANKS
        self._destroy.decay(self._discount)
        self._repair.decay(self._discount)
        self._destroy.credit(choice.destroy.value, credited)
        self._repair.credit(choice.repair.value, credited)
        self._routing_seconds += max(0.0, routing_seconds)
        if applied:
            self._applied += 1
        if self._pending == choice:
            self._pending = None

    def observe_and_select(
        self,
        metrics: OperatorMetrics,
        context: OperatorContext,
        *,
        routing_seconds: float = 0.0,
        applied: bool = True,
    ) -> OperatorChoice:
        """Credit the pending choice with what the router just did, then choose.

        The credit lands one evaluation late by design: an operator is paid by
        the realized routing outcome, never by a surrogate scored at selection
        time.  The first call has nothing pending and no baseline, and only
        selects.
        """
        pending = self._pending
        baseline = self._baseline
        if pending is not None and baseline is not None:
            self.observe(
                pending,
                reward_vector(
                    OperatorOutcome(
                        choice=pending,
                        before=baseline,
                        after=metrics,
                        applied=applied,
                    )
                ),
                applied=applied,
                routing_seconds=routing_seconds,
            )
        self._baseline = metrics
        return self.select(context)


def operator_tally(session: OperatorSession) -> str:
    """Per-arm play counts for both ledgers, in declaration order.

    Shaped ``destroy:<name>:<n>|...|repair:<name>:<n>`` so one placement stat
    carries the whole portfolio's usage without a second key per operator.
    """
    destroy = dict.fromkeys((operator for operator in DestroyOperator), 0)
    repair = dict.fromkeys((operator for operator in RepairOperator), 0)
    for choice in session.choices:
        destroy[choice.destroy] += 1
        repair[choice.repair] += 1
    parts = [
        f"destroy:{operator.value}:{count}"
        for operator, count in destroy.items()
        if count or operator in SHIPPED_DESTROY
    ]
    parts += [
        f"repair:{operator.value}:{count}"
        for operator, count in repair.items()
        if count or operator in SHIPPED_REPAIR
    ]
    return "|".join(parts)
