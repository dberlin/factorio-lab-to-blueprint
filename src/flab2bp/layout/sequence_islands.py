"""Spawn-isolated orchestration for complete sequence-pair solves."""

from __future__ import annotations

import multiprocessing
import time
from collections.abc import Sequence
from concurrent.futures import Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, replace
from typing import Literal

from flab2bp.layout import validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout, Placement
from flab2bp.layout.compact_seed import CompactSeedConfig
from flab2bp.layout.sequence_pair import derive_stage_seed
from flab2bp.layout.sequence_solver import (
    SequenceSolverConfig,
    _exact_key,
    _production_run,
    _serial_compact_seed_attempt,
    _with_observational_stats,
)
from flab2bp.spec import BuildSpec

_ISLAND_COMPLETION_GRACE_S = 90.0



@dataclass(frozen=True, slots=True)
class _SequenceIslandRequest:
    """Plain pickleable inputs for one complete production solve."""

    spec: BuildSpec
    time_budget_s: float
    soft_deadline: float
    power: bool
    band_policy: BandPolicy
    belt_vertical_construction: bool
    strip_len: int
    config: SequenceSolverConfig
    island_id: int
    seed: int
    compact_seed_attempt: int | None
    compact_seed_base_seed: int
    compact_seed_config: CompactSeedConfig


@dataclass(frozen=True, slots=True)
class _SequenceIslandOutcome:
    """One exact result, honest refusal, or validator rejection."""

    island_id: int
    seed: int
    status: Literal["completed", "refused", "invalid"]
    placement: Placement | None = None
    refusal_reason: str | None = None
    refusal_spec_label: str = ""
    refusal_budget_s: float = 0.0

    @classmethod
    def completed(
        cls,
        island_id: int,
        seed: int,
        placement: Placement,
    ) -> _SequenceIslandOutcome:
        return cls(island_id, seed, "completed", placement)

    @classmethod
    def refused(
        cls,
        island_id: int,
        seed: int,
        reason: str,
        spec_label: str,
        budget_s: float,
    ) -> _SequenceIslandOutcome:
        return cls(
            island_id,
            seed,
            "refused",
            refusal_reason=reason,
            refusal_spec_label=spec_label,
            refusal_budget_s=budget_s,
        )

    @classmethod
    def invalid(
        cls,
        island_id: int,
        seed: int,
        placement: Placement,
    ) -> _SequenceIslandOutcome:
        return cls(island_id, seed, "invalid", placement)


def _sequence_island_seeds(base_seed: int, islands: int) -> tuple[int, ...]:
    """Preserve the serial seed at island zero and derive every later seed."""
    return (base_seed,) + tuple(
        derive_stage_seed(base_seed, island_id) for island_id in range(1, islands)
    )




def _sequence_island_deadlines(
    time_budget_s: float,
    *,
    started: float,
) -> tuple[float, float, float]:
    """Return requested search time, child deadline, and bounded completion deadline."""
    ceiling = time_budget_s
    search_deadline = started + ceiling
    completion_grace = _ISLAND_COMPLETION_GRACE_S if ceiling > 0 else 0.0
    return ceiling, search_deadline, search_deadline + completion_grace


def _run_sequence_island(request: _SequenceIslandRequest) -> _SequenceIslandOutcome:
    """Reconstruct and run one production solver entirely inside a child."""
    config = replace(request.config, seed=request.seed)
    try:
        run = _production_run(
            request.spec,
            time_budget_s=request.time_budget_s,
            power=request.power,
            band_policy=request.band_policy,
            belt_vertical_construction=request.belt_vertical_construction,
            strip_len=request.strip_len,
            config=config,
            absolute_deadline=request.soft_deadline,
            compact_seed_attempt=request.compact_seed_attempt,
            compact_seed_base_seed=request.compact_seed_base_seed,
            compact_seed_config=request.compact_seed_config,
        )
        result = run.solver.search()
        placement = _with_observational_stats(result, run, request.power, config)
    except NoValidLayout as exc:
        return _SequenceIslandOutcome.refused(
            request.island_id,
            request.seed,
            exc.reason,
            exc.spec_label,
            exc.budget_s,
        )

    if validate.certify(placement, request.spec, expect_power=request.power).errors:
        return _SequenceIslandOutcome.invalid(request.island_id, request.seed, placement)
    return _SequenceIslandOutcome.completed(request.island_id, request.seed, placement)


def _completed_placement(outcome: _SequenceIslandOutcome) -> Placement:
    placement = outcome.placement
    if placement is None:
        raise RuntimeError(
            f"completed sequence island {outcome.island_id} returned no placement"
        )
    return placement


def _merge_sequence_island_outcomes(
    outcomes: Sequence[_SequenceIslandOutcome],
    *,
    requested: int,
    spec_label: str,
    budget_s: float,
) -> _SequenceIslandOutcome:
    """Select an exact result by quality and id, never by completion order."""
    completed = tuple(
        outcome
        for outcome in outcomes
        if outcome.status == "completed" and outcome.placement is not None
    )
    if completed:
        return min(
            completed,
            key=lambda outcome: (
                *_exact_key(_completed_placement(outcome)),
                outcome.island_id,
            ),
        )

    invalid = tuple(outcome for outcome in outcomes if outcome.status == "invalid")
    if invalid:
        ids = ", ".join(str(outcome.island_id) for outcome in sorted(invalid, key=_island_id))
        raise RuntimeError(f"sequence islands returned validator-rejected placements: {ids}")

    refused = sorted(
        (outcome for outcome in outcomes if outcome.status == "refused"),
        key=_island_id,
    )
    details = "; ".join(
        f"island {outcome.island_id}: {outcome.refusal_reason}" for outcome in refused
    )
    raise NoValidLayout(
        f"all {requested} sequence islands refused" + (f": {details}" if details else ""),
        spec_label=spec_label,
        budget_s=budget_s,
    )


def _island_id(outcome: _SequenceIslandOutcome) -> int:
    return outcome.island_id


def _terminate_executor(
    executor: ProcessPoolExecutor,
    futures: Sequence[Future[_SequenceIslandOutcome]],
) -> None:
    """Stop queued and active children without waiting for their solve ceiling."""
    for future in futures:
        _ = future.cancel()
    try:
        executor.terminate_workers()
    except BaseException:
        try:
            executor.kill_workers()
        except BaseException:
            executor.shutdown(wait=False, cancel_futures=True)


def _island_stats(
    winner: _SequenceIslandOutcome,
    outcomes: Sequence[_SequenceIslandOutcome],
    *,
    requested: int,
    result_reserve_s: float,
) -> Placement:
    placement = _completed_placement(winner)
    stats = placement.stats.copy()
    stats.update(
        {
            "islands_requested": float(requested),
            "islands_completed": float(len(outcomes)),
            "islands_refused": float(sum(outcome.status == "refused" for outcome in outcomes)),
            "island_result_reserve_s": result_reserve_s,
            "winner_island_id": winner.island_id,
            "winner_island_seed": winner.seed,
        }
    )
    return replace(placement, stats=stats)


def run_sequence_islands(
    spec: BuildSpec,
    *,
    time_budget_s: float,
    power: bool,
    band_policy: BandPolicy,
    belt_vertical_construction: bool,
    strip_len: int,
    config: SequenceSolverConfig,
    compact_seed_config: CompactSeedConfig,
    islands: int,
) -> Placement:
    """Run complete production solves in fresh spawned children and merge them."""
    ceiling, soft_deadline, hard_deadline = _sequence_island_deadlines(
        time_budget_s,
        started=time.monotonic(),
    )
    seeds = _sequence_island_seeds(config.seed, islands)
    serial_attempt = _serial_compact_seed_attempt(
        spec.machine_count,
        len(spec.spray_lanes),
        power=power,
    )
    compact_attempts = (serial_attempt,) + tuple(
        attempt for attempt in range(islands) if attempt != serial_attempt
    )
    requests = tuple(
        _SequenceIslandRequest(
            spec=spec,
            time_budget_s=time_budget_s,
            soft_deadline=soft_deadline,
            power=power,
            band_policy=band_policy,
            belt_vertical_construction=belt_vertical_construction,
            strip_len=strip_len,
            config=config,
            island_id=island_id,
            seed=seed,
            compact_seed_attempt=compact_attempts[island_id],
            compact_seed_base_seed=config.seed,
            compact_seed_config=compact_seed_config,
        )
        for island_id, seed in enumerate(seeds)
    )
    executor = ProcessPoolExecutor(
        max_workers=islands,
        mp_context=multiprocessing.get_context("spawn"),
        max_tasks_per_child=1,
    )
    futures: list[Future[_SequenceIslandOutcome]] = []
    future_ids: dict[Future[_SequenceIslandOutcome], int] = {}
    terminated = False
    try:
        for request in requests:
            future = executor.submit(_run_sequence_island, request)
            futures.append(future)
            future_ids[future] = request.island_id
        done, not_done = wait(
            futures,
            timeout=max(0.0, hard_deadline - time.monotonic()),
        )
        outcomes = tuple(future.result() for future in sorted(done, key=future_ids.__getitem__))
        if not_done:
            _terminate_executor(executor, futures)
            terminated = True
    except BaseException:
        if not terminated:
            _terminate_executor(executor, futures)
        raise
    else:
        if not terminated:
            executor.shutdown(wait=True, cancel_futures=False)

    if not_done and not any(outcome.status == "completed" for outcome in outcomes):
        if any(outcome.status == "invalid" for outcome in outcomes):
            _merge_sequence_island_outcomes(
                outcomes,
                requested=islands,
                spec_label=spec.label,
                budget_s=ceiling,
            )
        raise NoValidLayout(
            "deadline exhausted before any sequence island produced an exact layout",
            spec_label=spec.label,
            budget_s=ceiling,
        )
    winner = _merge_sequence_island_outcomes(
        outcomes,
        requested=islands,
        spec_label=spec.label,
        budget_s=ceiling,
    )
    return _island_stats(
        winner,
        outcomes,
        requested=islands,
        result_reserve_s=hard_deadline - soft_deadline,
    )
