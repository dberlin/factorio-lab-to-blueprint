"""Construct and certify transport geometry inside an already supervised process."""

from __future__ import annotations

import math
import time
from dataclasses import replace

from flab2bp.dsp import catalog
from flab2bp.layout import finalize, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import (
    NoValidLayout,
    Placement,
    PlacementCompletion,
    PlacementStats,
    ProjectionFailureRecord,
)
from flab2bp.layout.belt_tiers import retier_belts
from flab2bp.spec import BuildSpec

from .budget import TransportRefusal, WorkBudget


class TransportRoutingKernel:
    """Unsupervised worker implementation shared by serial and portfolio ownership."""

    def __init__(self, *, belt_rules: catalog.BeltAltitudeRules, band_policy: BandPolicy) -> None:
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
        deadline = (
            time.monotonic() + time_budget_s if absolute_deadline is None else absolute_deadline
        )
        from flab2bp.layout import routing_domain as rd

        from .composition import construct
        from .construction import ConstructionRefusal
        from .routing import RoutingRun

        started = time.monotonic()
        budget = WorkBudget(deadline)
        session = RoutingRun(budget)
        stage = "construction"

        def statistics() -> PlacementStats:
            return {
                "total_time_s": time.monotonic() - started,
                "transport_stage": stage,
                "transport_work_arcs": budget.counts.get("arcs", 0),
                "transport_work_augmentations": budget.counts.get("augmentations", 0),
                "transport_work_candidates": budget.counts.get("candidates", 0),
                "transport_work_audit_cells": budget.counts.get("audit_cells", 0),
                "transport_work_predicates": budget.counts.get("predicates", 0),
                "transport_work_assignments": budget.counts.get("assignments", 0),
            }

        def project_candidate(placement: Placement) -> Placement:
            nonlocal stage
            previous_stage = stage
            try:
                stage = "belt-tier-selection"
                budget.check()
                placement = retier_belts(placement, spec)
                stage = "compaction"
                budget.check()
                placement = finalize.compact_open_boundary_belts(
                    placement, spec, expect_power=True, belt_rules=self.belt_rules
                )
                stage = "projection"
                budget.check()
                placement = finalize.finalize_placement(
                    placement,
                    self.band_policy,
                    cancelled=lambda: budget.clock() >= budget.deadline,
                )
            except finalize.ProjectionRefusal:
                stage = previous_stage
                raise
            stage = previous_stage
            return placement

        try:
            placement = construct(
                spec,
                self.belt_rules,
                self.band_policy,
                session,
                project_candidate=project_candidate,
            )
            stage = "certification"
            budget.check()
            report = validate.certify(
                placement, spec, belt_rules=self.belt_rules, expect_power=True
            )
            if report.errors or report.skipped:
                raise TransportRefusal(
                    "VALIDATION_FAILURE",
                    "; ".join(str(error) for error in report.errors)
                    or f"validator skipped {report.skipped}",
                )
            budget.check()
        except finalize.ProjectionRefusal as exc:
            raise NoValidLayout(
                str(exc),
                spec_label=spec.label,
                budget_s=time_budget_s,
                projection_failures=tuple(
                    ProjectionFailureRecord(
                        failure.band, failure.check, failure.buildings, failure.detail
                    )
                    for failure in exc.failures
                ),
                stats={
                    key: value
                    for key, value in statistics().items()
                    if isinstance(value, (float, int, str))
                },
            ) from exc
        except (finalize.ProjectionCancelled, rd._PreparationDeadline) as exc:
            raise NoValidLayout(
                f"DEADLINE: transport-routing stopped during {stage}",
                spec_label=spec.label,
                budget_s=time_budget_s,
                stats={
                    key: value
                    for key, value in statistics().items()
                    if isinstance(value, (float, int, str))
                },
            ) from exc
        except (TransportRefusal, ConstructionRefusal) as exc:
            reason = (
                f"{exc.reason}: {exc.detail}" if isinstance(exc, TransportRefusal) else str(exc)
            )
            raise NoValidLayout(
                reason,
                spec_label=spec.label,
                budget_s=time_budget_s,
                stats={
                    key: value
                    for key, value in statistics().items()
                    if isinstance(value, (float, int, str))
                },
            ) from exc
        stage = "complete"
        placement.stats.update(statistics())
        placement.stats["belt_tiles"] = sum(
            catalog.is_belt(building.item_id) for building in placement.buildings
        )
        return replace(placement, completion=PlacementCompletion.COMPACTED_AND_FINALIZED)
