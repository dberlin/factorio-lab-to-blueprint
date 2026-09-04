"""Plan deterministic lane merges and the pilers that make them possible."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from flab2bp import spec
from flab2bp.dsp import catalog

__all__ = ["LaneLoad", "MergePlan", "PilerPlan", "plan_merges"]


@dataclass(frozen=True, slots=True)
class LaneLoad:
    """One producer lane's demand before any tail-end piling."""

    lane_id: str
    strip_ordinal: int
    demand: Fraction
    stack: int


@dataclass(frozen=True, slots=True)
class PilerPlan:
    """Pilers placed in series at one lane's tail."""

    lane_id: str
    count: int
    stack: int


@dataclass(frozen=True, slots=True)
class MergePlan:
    """A target stack and the lanes sharing each resulting belt."""

    stack: int
    groups: tuple[tuple[str, ...], ...]
    pilers: tuple[PilerPlan, ...]


def _pilers_in_series(from_stack: int, to_stack: int) -> int:
    """Return the number of doubling pilers needed to reach ``to_stack``."""
    count = 0
    stack = from_stack
    while stack < to_stack:
        stack = catalog.piler_output_stack(stack)
        count += 1
    return count


def plan_merges(
    loads: Sequence[LaneLoad],
    *,
    lane_capacity: Fraction,
    max_stack: int,
    sink_pick_stack: int,
) -> MergePlan:
    """Plan tail-end piling and capacity-safe lane groups in strip order."""
    if not loads:
        raise ValueError("merge planning requires at least one lane load")
    if lane_capacity <= 0:
        raise ValueError("lane capacity must be positive")
    if max_stack <= 0:
        raise ValueError("maximum stack must be positive")
    if sink_pick_stack <= 0:
        raise ValueError("sink pick stack must be positive")

    ordered = sorted(loads, key=lambda load: load.strip_ordinal)
    lane_ids: set[str] = set()
    for index, load in enumerate(ordered):
        if load.lane_id in lane_ids:
            raise ValueError("lane ids must be unique")
        lane_ids.add(load.lane_id)
        if index and load.strip_ordinal == ordered[index - 1].strip_ordinal:
            raise ValueError("strip ordinals must be unique")
        if load.demand <= 0:
            raise ValueError("lane demand must be positive")
        if not 1 <= load.stack <= catalog.PILER_MAX_STACK:
            raise ValueError(f"lane stack must be within 1..{catalog.PILER_MAX_STACK}")

    limit = min(max_stack, sink_pick_stack)
    candidates = tuple(stack for stack in spec.PILER_LADDER if stack <= limit)
    total = sum((load.demand for load in ordered), Fraction(0))
    selected_stack = candidates[-1]
    for candidate in candidates:
        if total / candidate <= lane_capacity:
            selected_stack = candidate
            break

    pilers = tuple(
        PilerPlan(
            lane_id=load.lane_id,
            count=_pilers_in_series(load.stack, selected_stack),
            stack=selected_stack,
        )
        for load in ordered
        if load.stack < selected_stack
    )

    lane_ids_in_order = tuple(load.lane_id for load in ordered)
    if total / selected_stack <= lane_capacity:
        return MergePlan(
            stack=selected_stack,
            groups=(lane_ids_in_order,),
            pilers=pilers,
        )

    groups: list[tuple[str, ...]] = []
    current: list[str] = []
    current_demand = Fraction(0)
    for load in ordered:
        demand = load.demand / max(load.stack, selected_stack)
        if current and current_demand + demand > lane_capacity:
            groups.append(tuple(current))
            current = []
            current_demand = Fraction(0)
        current.append(load.lane_id)
        current_demand += demand
    groups.append(tuple(current))

    return MergePlan(stack=selected_stack, groups=tuple(groups), pilers=pilers)
