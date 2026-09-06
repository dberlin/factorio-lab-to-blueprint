"""Cut pressure: the register-pressure analogue for a recipe DAG.

Throwaway spike code.

For a boundary between two sets of machines:

* ``item_pressure`` -- how many distinct items are produced on one side and
  consumed on the other. The number of *nets* that must cross.
* ``lane_pressure`` -- ``sum(ceil(rate / lane capacity))`` over those items. The
  number of *belts* that must cross, which is the thing the geometry actually
  pays for: an item at 4x the belt rate costs four lanes, not one net.

Lane capacity is ``spec.lane_capacity`` (the fastest belt the save allows) times
the planning stack, so a stacked bus is priced at what it really carries.

The second half of this module cuts by DEPTH instead of by size: the recipe DAG
is levelled, the pressure of every depth boundary is computed, and blocks are
formed between the boundaries where pressure is locally minimal -- keeping a
high-pressure region together as one block however large it is. That is the
"cut at pressure minima" rule, and `run.py --arm depth-pressure` runs it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from fractions import Fraction

from partition import Unit

from flab2bp.spec import BuildSpec


def lane_capacity(spec: BuildSpec, item: str) -> Fraction:
    """Items/second one lane of ``item`` carries, stack included."""
    try:
        stack = spec.planning_stack(item)
    except Exception:  # noqa: BLE001 - an unpickable bus is a plan-time refusal
        stack = 1
    return spec.lane_capacity * stack


def lanes_for(spec: BuildSpec, item: str, rate: Fraction) -> int:
    if rate <= 0:
        return 0
    capacity = lane_capacity(spec, item)
    return max(1, math.ceil(rate / capacity))


def cut_pressure(
    spec: BuildSpec, blocks: list[list[Unit]]
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Pressure for the whole partition and for each ordered block boundary.

    A boundary's items are those with surplus on the producing side and deficit
    on the consuming side, at the rate that actually has to cross.
    """
    surplus: dict[str, dict[int, Fraction]] = defaultdict(dict)
    deficit: dict[str, dict[int, Fraction]] = defaultdict(dict)
    for i, block in enumerate(blocks):
        made: dict[str, Fraction] = defaultdict(Fraction)
        took: dict[str, Fraction] = defaultdict(Fraction)
        for u in block:
            for item in u.group.outputs_per_machine:
                made[item] += u.produces(item)
            for item in u.group.inputs_per_machine:
                took[item] += u.consumes(item)
        for item in set(made) | set(took):
            net = made.get(item, Fraction(0)) - took.get(item, Fraction(0))
            if net > 0:
                surplus[item][i] = net
            elif net < 0:
                deficit[item][i] = -net

    per_pair: dict[tuple[int, int], dict[str, Fraction]] = defaultdict(dict)
    for item, wants in deficit.items():
        gives = surplus.get(item, {})
        for dst, want in wants.items():
            for src, give in gives.items():
                per_pair[(src, dst)][item] = min(give, want)

    boundaries: list[dict[str, object]] = []
    for (src, dst), items in sorted(per_pair.items()):
        boundaries.append(
            {
                "from": src,
                "to": dst,
                "item_pressure": len(items),
                "lane_pressure": sum(lanes_for(spec, i, r) for i, r in items.items()),
                "items": {i: str(r) for i, r in sorted(items.items())},
            }
        )

    # The whole partition's pressure counts each crossing ITEM once per
    # consuming block, because that is how many lanes the geometry has to build.
    total_items = sum(len(wants) for item, wants in deficit.items())
    total_lanes = sum(
        lanes_for(spec, item, want) for item, wants in deficit.items() for want in wants.values()
    )
    summary = {
        "item_pressure": total_items,
        "lane_pressure": total_lanes,
        "distinct_crossing_items": len(deficit),
        "boundaries": len(boundaries),
        "max_boundary_lane_pressure": max((b["lane_pressure"] for b in boundaries), default=0),
    }
    return summary, boundaries


# --- depth levelling and the pressure profile --------------------------------


def recipe_depths(spec: BuildSpec) -> dict[str, int]:
    """Longest-path depth of each recipe from the external inputs."""
    producers: dict[str, list[str]] = defaultdict(list)
    for g in spec.groups:
        for item in g.outputs_per_machine:
            producers[item].append(g.recipe_id)
    by_recipe = {g.recipe_id: g for g in spec.groups}
    depth: dict[str, int] = {}

    def resolve(recipe: str, stack: frozenset[str]) -> int:
        if recipe in depth:
            return depth[recipe]
        if recipe in stack:
            return 0  # a coproduct cycle; break it rather than recurse forever
        best = 0
        for item in by_recipe[recipe].inputs_per_machine:
            for upstream in producers.get(item, ()):
                if upstream == recipe:
                    continue
                best = max(best, 1 + resolve(upstream, stack | {recipe}))
        depth[recipe] = best
        return best

    for recipe in by_recipe:
        resolve(recipe, frozenset())
    return depth


def depth_profile(spec: BuildSpec) -> list[dict[str, object]]:
    """Pressure of every boundary between depth <= d and depth > d."""
    depth = recipe_depths(spec)
    levels = sorted(set(depth.values()))
    rows: list[dict[str, object]] = []
    for d in levels[:-1]:
        made: dict[str, Fraction] = defaultdict(Fraction)
        taken_above: dict[str, Fraction] = defaultdict(Fraction)
        for g in spec.groups:
            if depth[g.recipe_id] <= d:
                for item, rate in g.outputs_per_machine.items():
                    made[item] += rate * g.count
            else:
                for item, rate in g.inputs_per_machine.items():
                    taken_above[item] += rate * g.count
        crossing = {
            item: min(made[item], taken_above[item]) for item in made if item in taken_above
        }
        rows.append(
            {
                "cut_after_depth": d,
                "recipes_below": sum(1 for r in depth.values() if r <= d),
                "machines_below": sum(g.count for g in spec.groups if depth[g.recipe_id] <= d),
                "item_pressure": len(crossing),
                "lane_pressure": sum(lanes_for(spec, i, r) for i, r in crossing.items()),
                "items": sorted(crossing),
            }
        )
    return rows


def depth_pressure_blocks(spec: BuildSpec) -> tuple[list[list[Unit]], list[int], list[dict]]:
    """Blocks formed by cutting at the LOCAL MINIMA of the depth pressure profile.

    A region between two chosen cuts stays together as one block however many
    machines it holds -- that is the whole point of the arm: high-pressure
    regions are solved integrated, and the knife goes where few belts cross.
    """
    profile = depth_profile(spec)
    if not profile:
        cut_depths: list[int] = []
    else:
        lanes = [int(row["lane_pressure"]) for row in profile]
        cut_depths = []
        for k, row in enumerate(profile):
            left = lanes[k - 1] if k else 1 << 30
            right = lanes[k + 1] if k + 1 < len(lanes) else 1 << 30
            if lanes[k] <= left and lanes[k] <= right:
                cut_depths.append(int(row["cut_after_depth"]))

    depth = recipe_depths(spec)
    uid = [5_000_000]
    blocks: list[list[Unit]] = []
    bands: list[tuple[int, int]] = []
    lo = min(depth.values(), default=0)
    hi = max(depth.values(), default=0)
    edges = [*sorted(cut_depths), hi]
    start = lo
    for edge in edges:
        if edge < start:
            continue
        bands.append((start, edge))
        start = edge + 1
    for band_lo, band_hi in bands:
        members = [g for g in spec.groups if band_lo <= depth[g.recipe_id] <= band_hi]
        if not members:
            continue
        block: list[Unit] = []
        for g in members:
            block.append(Unit(uid[0], g, g.count))
            uid[0] += 1
        blocks.append(block)
    return blocks, sorted(cut_depths), profile
