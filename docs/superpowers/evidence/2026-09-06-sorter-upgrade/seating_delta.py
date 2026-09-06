"""Which families' seatings the servability preference actually moves.

Usage: uv run python .../seating_delta.py <url>
Prints one line per family whose default variant's lane rows changed, with the
old and new (item, span, rate, ceiling) rows.
"""

from __future__ import annotations

import sys
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout import freeform, strip_variants
from flab2bp.layout.strip_variants import default_strip_variant, generate_strip_families
from flab2bp.rates.candidates import CandidatePolicy, build_candidates


def rows(spec, family):  # type: ignore[no-untyped-def]
    group = freeform._adapt(spec)[family.group_key]
    variant = default_strip_variant(family)
    out = []
    for plan in variant.attachment_plan:
        rates = group.inputs if plan.lane.kind == "input" else group.outputs
        for att in plan.attachments:
            rate = rates.get(att.item, Fraction(0))
            ceiling = strip_variants._fastest_lane_rate(spec, att.item, att.span)
            out.append(
                (plan.lane.lane_id, plan.lane_y, att.span, att.item, float(rate), float(ceiling))
            )
    return tuple(out)


def main(url: str, policy: str) -> int:
    data = load_vendored()
    request = parse_url(url)
    spec = build_candidates(
        data, request, candidate_policies=(CandidatePolicy(policy),)
    ).candidates[0]
    after = {f.family_id: (f.recipe_id, rows(spec, f)) for f in generate_strip_families(spec)}

    real = strip_variants._side_rows_serve
    strip_variants._side_rows_serve = lambda *a, **k: True  # type: ignore[assignment]
    try:
        before = {f.family_id: (f.recipe_id, rows(spec, f)) for f in generate_strip_families(spec)}
    finally:
        strip_variants._side_rows_serve = real  # type: ignore[assignment]

    moved = 0
    for key in sorted(set(before) | set(after), key=str):
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        moved += 1
        print(f"MOVED {key}")
        print("  before:", old)
        print("  after :", new)
    print(f"{moved} of {len(after)} families moved")
    print("catalog check:", catalog.SORTER_TIERS)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "output-products"))
