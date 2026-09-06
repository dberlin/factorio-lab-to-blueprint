"""Per-lane sorter sizing for every strip family this URL plans.

For each input/output lane of each family, print the row it was seated on, the
span its sorter must cross, the per-machine rate it must move, the tier the
picker chose and that tier's capacity -- and flag the lanes no allowed tier can
carry at that span.

Run: uv run python docs/superpowers/evidence/2026-09-06-sorter-upgrade/lane_seating.py
"""

from __future__ import annotations

import sys
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request
from flab2bp.lab.url import parse_url
from flab2bp.layout import freeform
from flab2bp.layout.strip_variants import default_strip_variant, generate_strip_families
from flab2bp.rates.candidates import build_candidates

from characterise import URL  # type: ignore[import-not-found]


def main() -> int:
    data = canonicalize_dataset(load_vendored())
    request = canonicalize_request(parse_url(URL))
    specs = build_candidates(data, request).candidates
    for spec in specs:
        print(f"\n=== candidate {spec.label} ===")
        print("external_inputs:", sorted(spec.external_inputs))
        groups = freeform._adapt(spec)
        tiers = freeform._sorter_tiers_for(spec)
        stacks = freeform._sorter_stacks_for(spec)
        lane_stacks = freeform._lane_stacks_for(spec)
        for family in generate_strip_families(spec):
            group = groups[family.group_key]
            if not family.variants:
                print(f"  {family.recipe_id}: no physical variant")
                continue
            variant = default_strip_variant(family)
            print(
                f"  {family.recipe_id} on {catalog.building(family.machine_item_id).name} "
                f"x{family.total_machine_count} yaw={variant.yaw}"
            )
            for plan in variant.attachment_plan:
                lane = plan.lane
                rates = group.inputs if lane.kind == "input" else group.outputs
                for att in plan.attachments:
                    rate = rates.get(att.item, Fraction(0))
                    tier, _ = freeform._pick_sorter(
                        rate,
                        att.span,
                        1,
                        tiers,
                        stacks=stacks,
                        min_pick_stack=(
                            lane_stacks.into(att.item) if lane.kind == "input" else 1
                        ),
                        min_place_stack=(
                            1 if lane.kind == "input" else lane_stacks.out_of(att.item)
                        ),
                    )
                    cap = catalog.sorter_rate(tier, att.span)
                    best = max(catalog.sorter_rate(t, att.span) for t in tiers)
                    short = " <-- OVER CAPACITY" if rate > cap else ""
                    fixable = ""
                    if rate > cap:
                        ok = [s for s in (1, 2, 3) if max(
                            catalog.sorter_rate(t, s) for t in tiers
                        ) >= rate]
                        fixable = f" (spans that would carry it: {ok})"
                    print(
                        f"    {lane.lane_id:>16} y={plan.lane_y:>3} span={att.span} "
                        f"{att.item:<24} rate={float(rate):7.3f}/s tier={tier} "
                        f"cap={float(cap):7.3f} best_tier_cap={float(best):7.3f}"
                        f"{short}{fixable}"
                    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
