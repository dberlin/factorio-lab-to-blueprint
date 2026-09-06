"""Is ANY generated strip variant able to carry the casimir strip's hydrogen?

Walks every variant of every family (all yaws, all seatings) and reports, per
family, whether some variant seats every input/output attachment at a span the
save's fastest sorter can sustain.

Run: uv run python docs/superpowers/evidence/2026-09-06-sorter-upgrade/variant_search.py
"""

from __future__ import annotations

import sys
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request
from flab2bp.lab.url import parse_url
from flab2bp.layout import freeform
from flab2bp.layout.strip_variants import generate_strip_families, lane_reach_profiles
from flab2bp.rates.candidates import build_candidates

from characterise import URL  # type: ignore[import-not-found]


def main() -> int:
    data = canonicalize_dataset(load_vendored())
    request = canonicalize_request(parse_url(URL))
    spec = next(
        s for s in build_candidates(data, request).candidates if s.label == "no-proliferator"
    )
    groups = freeform._adapt(spec)
    tiers = freeform._sorter_tiers_for(spec)
    stacks = freeform._sorter_stacks_for(spec)
    print("candidate:", spec.label)
    for family in generate_strip_families(spec):
        group = groups[family.group_key]
        if not family.variants:
            continue
        feasible = 0
        worst: list[str] = []
        for variant in family.variants:
            bad: list[str] = []
            for plan in variant.attachment_plan:
                rates = group.inputs if plan.lane.kind == "input" else group.outputs
                for att in plan.attachments:
                    rate = rates.get(att.item, Fraction(0))
                    cap = max(catalog.sorter_rate(t, att.span) for t in tiers) * max(
                        stacks.pick(t) if plan.lane.kind == "input" else stacks.place(t)
                        for t in tiers
                    )
                    plain = max(catalog.sorter_rate(t, att.span) for t in tiers)
                    if rate > plain:
                        bad.append(f"{att.item}@span{att.span} {float(rate):.2f}>{float(plain):.2f}")
                    del cap
            if not bad:
                feasible += 1
            elif not worst:
                worst = bad
        print(
            f"  {family.recipe_id}: {len(family.variants)} variants, "
            f"{feasible} sorter-feasible"
            + (f"; e.g. {worst}" if feasible == 0 else "")
        )
        if feasible == 0:
            item_id = family.machine_item_id
            print(f"    reach profiles for {catalog.building(item_id).name}:")
            for yaw in (0.0, 90.0, 180.0, 270.0):
                rows = [
                    (p.side, p.lane_y, tuple(sorted({a[1].span for a in p.attachments})),
                     len(p.attachments))
                    for p in lane_reach_profiles(item_id, yaw)
                ]
                print(f"      yaw {yaw}: {rows}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
