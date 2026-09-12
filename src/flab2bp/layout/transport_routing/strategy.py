"""Deadline-supervised constructive transport with ordinary production certification."""

from __future__ import annotations

import math
import time

from flab2bp.dsp import catalog
from flab2bp.layout import strategy_race
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout, Placement
from flab2bp.spec import BuildSpec

_DEFAULT_BAND_POLICY = BandPolicy("portable")


class TransportRoutingLayout:
    """Construct physical strip interfaces, then certify the completed placement.

    Serial callers own one spawned child. The portfolio factory selects the
    construction kernel directly inside its already supervised child.
    Neither path invokes the global router or changes the requested specification.
    """

    name = "transport-routing"

    def __init__(
        self,
        *,
        belt_rules: catalog.BeltAltitudeRules,
        band_policy: BandPolicy = _DEFAULT_BAND_POLICY,
    ) -> None:
        self.belt_rules = belt_rules
        self.band_policy = band_policy

    def lay_out(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement:
        if not math.isfinite(time_budget_s) or time_budget_s <= 0:
            raise ValueError("transport-routing requires a finite positive time budget")
        started = time.monotonic()
        deadline = started + time_budget_s if absolute_deadline is None else absolute_deadline
        if deadline <= started:
            raise NoValidLayout(
                "DEADLINE: transport-routing received an expired deadline",
                spec_label=spec.label,
                budget_s=time_budget_s,
            )
        request = strategy_race._StrategyRaceRequest(
            spec=spec,
            strategy="transport-routing",
            time_budget_s=time_budget_s,
            soft_deadline=deadline,
            band_policy=self.band_policy,
            belt_rules=self.belt_rules,
            workers=1,
            arrangements=None,
            sequence_islands=1,
            config=None,
            compact_seed_config=None,
            share=False,
        )
        futures, executor = strategy_race._pool_submit((request,), {})
        try:
            future = next(iter(futures))
            try:
                outcome = future.result(timeout=max(0.0, deadline - time.monotonic()))
            except TimeoutError as exc:
                raise NoValidLayout(
                    "DEADLINE: transport-routing child exceeded its absolute deadline",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                    stats={"total_time_s": time.monotonic() - started},
                ) from exc
            result = strategy_race._raced_result(outcome, spec.label, time_budget_s)
            if isinstance(result, NoValidLayout):
                raise result
            return result
        finally:
            strategy_race._terminate_executor(executor, tuple(futures))
