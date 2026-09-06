"""Characterise the sorter demand this URL asks of the save's fastest sorter.

Run: uv run python docs/superpowers/evidence/2026-09-06-sorter-upgrade/characterise.py
"""

from __future__ import annotations

import sys
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.lab.data import load_vendored
from flab2bp.lab.techs import logistics_tiers_for_request
from flab2bp.lab.url import parse_url
from flab2bp.layout import freeform
from flab2bp.rates.candidates import build_candidates
from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request

URL = (
    "https://factoriolab.github.io/dsp/list?z=eJzLt3Uq0zI1MFDLt3VK1jI0MNDSMgSxs5DYkQi2uZaRAVzcScsYSb0RjF2CYDolaxmZwtiVIOUIvYZwThUSuwCJHQFmw3SUI"
    ".PCtAwtLS2hMoEgC0GMMCijFEWjIdzIzKRUW2e1otQK23i13Nwi2-S64rrMusC6SrUyW0NDAPYfP-s_&v=11"
)


def main() -> int:
    data = canonicalize_dataset(load_vendored())
    request = canonicalize_request(parse_url(URL))
    researched = request.researched_technology_ids
    tiers = logistics_tiers_for_request(request, data)
    print("=== save ===")
    print("belt_id:", request.belt_id)
    print("researched set size:", None if researched is None else len(researched))
    print("sorter_item_ids:", tiers.sorter_item_ids)
    print("sorter_pick_stacks:", tiers.sorter_pick_stacks)
    print("sorter_place_stacks:", tiers.sorter_place_stacks)
    print("piler:", tiers.piler)
    print("belt_item_ids:", tiers.belt_item_ids)
    if researched is not None:
        print(
            "pile-sorter techs researched:",
            sorted(t for t in researched if "pile-sorter" in t or "stacking" in t),
        )
        print("integrated-logistics-system:", "integrated-logistics-system" in researched)
    print("SORTER_STACKING_LEVELS:", catalog.SORTER_STACKING_LEVELS)
    print("SORTER_STACK_RATE_FACTOR:", catalog.SORTER_STACK_RATE_FACTOR)

    specs = build_candidates(data, request).candidates
    for spec in specs:
        print()
        print("=== candidate:", spec.label, "===")
        print("belt:", spec.belt_item_id, spec.belt_items_per_second, "stack", spec.belt_stack)
        print("sorter_item_ids:", spec.sorter_item_ids)
        print("pick stacks:", spec.sorter_pick_stacks, "place stacks:", spec.sorter_place_stacks)
        print("piler_unlocked:", spec.piler_unlocked)
        print("groups:", len(spec.groups), "machines:", sum(g.count for g in spec.groups))
        sorter_tiers = freeform._sorter_tiers_for(spec)
        stacks = freeform._sorter_stacks_for(spec)
        lane_stacks = freeform._lane_stacks_for(spec)
        print("picker tiers (slow->fast):", sorter_tiers)
        print("pick_by_tier:", stacks.pick_by_tier, "place_by_tier:", stacks.place_by_tier)
        for g in spec.groups:
            for item, rate in sorted(g.inputs_per_machine.items()):
                if item != "hydrogen":
                    continue
                print(
                    f"  IN  {g.recipe_id} x{g.count} {item}: per-machine {rate} "
                    f"({float(rate):.3f}/s) total {rate * g.count}"
                )
            for item, rate in sorted(g.outputs_per_machine.items()):
                if item != "hydrogen":
                    continue
                print(
                    f"  OUT {g.recipe_id} x{g.count} {item}: per-machine {rate} "
                    f"({float(rate):.3f}/s) total {rate * g.count}"
                )
        print(
            "planning_stack(hydrogen, external=True):",
            spec.planning_stack("hydrogen"),
            " (external=False):",
            spec.planning_stack("hydrogen", external=False),
        )
        print("lane_stacks consumed[hydrogen]:", lane_stacks.consumed.get("hydrogen"))
        print("lane_stacks produced[hydrogen]:", lane_stacks.produced.get("hydrogen"))
        # What the picker returns for the convicted demand.
        for demand in (Fraction(8), Fraction(128, 15)):
            for span in (1, 2, 3):
                tier, count = freeform._pick_sorter(
                    demand,
                    span,
                    1,
                    sorter_tiers,
                    stacks=stacks,
                    min_place_stack=1,
                    min_pick_stack=1,
                )
                print(
                    f"  _pick_sorter({demand}, span={span}, machines=1) -> tier {tier} "
                    f"rate {catalog.sorter_rate(tier, span)}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
