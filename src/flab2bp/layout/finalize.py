"""Strategy-independent, validator-gated cleanup of exact placements."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Literal

from flab2bp.dsp import catalog
from flab2bp.layout.base import Placement
from flab2bp.layout.validate import certify as _certify
from flab2bp.spec import BuildSpec

type _Direction = Literal["input", "output"]
type _Side = Literal["left", "bottom", "right", "top"]




def _remove_buildings(placement: Placement, removed: frozenset[int]) -> Placement:
    """Remove indices, bypass their links, and rewrite every surviving reference."""
    if not removed:
        return placement
    size = len(placement.buildings)
    if any(index < 0 or index >= size for index in removed):
        raise ValueError("removed building indices must belong to the placement")
    if len(removed) == size:
        return placement

    mapping = {
        old: new
        for new, old in enumerate(index for index in range(size) if index not in removed)
    }

    def remap(value: int | None, direction: _Direction) -> int | None:
        seen: set[int] = set()
        while value is not None and value in removed and value not in seen:
            seen.add(value)
            building = placement.buildings[value]
            value = building.output_obj if direction == "output" else building.input_obj
        return mapping.get(value) if value is not None else None

    buildings = tuple(
        replace(
            building,
            output_obj=remap(building.output_obj, "output"),
            input_obj=remap(building.input_obj, "input"),
        )
        for index, building in enumerate(placement.buildings)
        if index not in removed
    )
    candidate = replace(placement, buildings=buildings)
    stats = placement.stats.copy()
    if "area" in stats:
        stats["area"] = float(candidate.area)
    if "belt_tiles" in stats:
        belt_tiles = stats["belt_tiles"]
        stats["belt_tiles"] = float(belt_tiles) - len(removed)
    return replace(candidate, stats=stats)


def _prunable_open_belts(placement: Placement) -> frozenset[int]:
    """Unreferenced outer belt leaves that can be removed as one structural wave."""
    buildings = placement.buildings
    belts = {
        index
        for index, building in enumerate(buildings)
        if catalog.is_belt(building.item_id)
    }
    predecessors: dict[int, set[int]] = {index: set() for index in belts}
    for index in belts:
        target = buildings[index].output_obj
        if target in belts:
            predecessors[target].add(index)
    nonbelt_references = {
        target
        for index, building in enumerate(buildings)
        if index not in belts
        for target in (building.input_obj, building.output_obj)
        if target in belts
    }
    left, bottom, right, top = placement.bounds
    selected: set[int] = set()
    for index in belts:
        building = buildings[index]
        successor = building.output_obj if building.output_obj in belts else None
        neighbours = len(predecessors[index]) + int(successor is not None)
        open_end = not predecessors[index] or successor is None
        outer = (
            building.x == left
            or building.x + building.width - 1 == right
            or building.y == bottom
            or building.y + building.height - 1 == top
        )
        protected = index in nonbelt_references or bool(building.parameters)
        if outer and open_end and not protected and neighbours <= 1:
            selected.add(index)
    return frozenset(selected)


def _boundary_open_belts(placement: Placement, side: _Side) -> frozenset[int]:
    """Open belts on one current bounding side for the certified fallback."""
    left, bottom, right, top = placement.bounds
    return frozenset(
        index
        for index, building in enumerate(placement.buildings)
        if catalog.is_belt(building.item_id)
        and (building.input_obj is None or building.output_obj is None)
        and (
            (side == "left" and building.x == left)
            or (side == "bottom" and building.y == bottom)
            or (side == "right" and building.x + building.width - 1 == right)
            or (side == "top" and building.y + building.height - 1 == top)
        )
    )




def uses_tall_saturated_role(
    *,
    machine_count: float,
    strip_count: float,
    sprayed_lanes: int,
) -> bool:
    """Whether the shared pack/cleanup should use the tall saturated role."""
    return (
        sprayed_lanes > 0
        and 13 < strip_count <= 24
        and machine_count >= 4 * strip_count
    )


def _certified_side_fallback(
    placement: Placement,
    spec: BuildSpec,
    *,
    expect_power: bool,
) -> tuple[Placement, int]:
    """Use bounded side batches when structural pruning breaks addon geometry."""
    compacted = placement
    removed_total = 0

    def attempt(removed: frozenset[int]) -> bool:
        nonlocal compacted, removed_total
        candidate = _remove_buildings(compacted, removed)
        if candidate is compacted or candidate.area >= compacted.area:
            return False
        errors = _certify(candidate, spec, expect_power=expect_power).errors
        if errors:
            return False
        compacted = candidate
        removed_total += len(removed)
        return True

    machines = placement.stats.get("machines", 0.0)
    strips = placement.stats.get("strips", 0.0)
    if uses_tall_saturated_role(
        machine_count=float(machines),
        strip_count=float(strips),
        sprayed_lanes=len(spec.spray_lanes),
    ):
        for side in ("left", "bottom", "right", "top"):
            _ = attempt(_boundary_open_belts(compacted, side))
    else:
        for _round in range(4):
            removed = _boundary_open_belts(compacted, "left") | _boundary_open_belts(
                compacted, "bottom"
            )
            if not attempt(removed):
                break
    return compacted, removed_total


def compact_open_boundary_belts(
    placement: Placement,
    spec: BuildSpec,
    *,
    expect_power: bool,
) -> Placement:
    """Prune structural belt leaves once, with a bounded certified fallback."""
    started = time.perf_counter()
    compacted = placement
    removed_total = 0
    for _wave in range(len(placement.buildings)):
        removed = _prunable_open_belts(compacted)
        if not removed:
            break
        candidate = _remove_buildings(compacted, removed)
        if candidate is compacted:
            break
        compacted = candidate
        removed_total += len(removed)

    structural_errors = (
        _certify(compacted, spec, expect_power=expect_power).errors
        if compacted is not placement
        else ()
    )
    tall_role = uses_tall_saturated_role(
        machine_count=float(placement.stats.get("machines", 0.0)),
        strip_count=float(placement.stats.get("strips", 0.0)),
        sprayed_lanes=len(spec.spray_lanes),
    )
    if compacted is placement or structural_errors:
        compacted, removed_total = _certified_side_fallback(
            placement,
            spec,
            expect_power=expect_power,
        )
    elif tall_role:
        compacted, side_removed = _certified_side_fallback(
            compacted,
            spec,
            expect_power=expect_power,
        )
        removed_total += side_removed
    if compacted is placement:
        return placement
    stats = compacted.stats.copy()
    stats["boundary_belts_removed"] = float(removed_total)
    stats["boundary_cleanup_time_s"] = time.perf_counter() - started
    return replace(compacted, stats=stats)
