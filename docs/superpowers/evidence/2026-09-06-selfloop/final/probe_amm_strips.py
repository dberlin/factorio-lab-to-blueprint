"""Plan-level probe of the REPORTED AMM URL, for spec §9 R2's universality claim.

R2 closed with "Exactly one plan in the whole corpus is flanked
(`universe-matrix#37`), so nothing else can move."  That is a claim about the
CORPUS being read as a claim about every spec.  The reported URL is not in the
corpus, so this probe asks the same question of it directly.

Plan level ONLY -- `generate_strip_families` and `plan_strips`.  No packing, no
routing, no validation, no build.  Runs unchanged on master and on the branch
(every branch-only field is read through `getattr` with the master default), so
the two trees can be diffed line for line.

Prints, per candidate policy: one line per strip family (flanked, drain row,
machine cap, machines) and one line per planned strip, then the whole-spec
`total_box_height` that R2's cost argument is denominated in.
"""

from __future__ import annotations

from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout.freeform import plan_strips
from flab2bp.layout.strip_variants import generate_strip_families
from flab2bp.rates.candidates import CandidatePolicy, build_candidates

AMM_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJ"
    "FiWUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIg"
    "a9DKloJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11"
)

_POLICIES = (
    CandidatePolicy.NO_PROLIFERATOR,
    CandidatePolicy.ALL_PRODUCTS,
    CandidatePolicy.OUTPUT_PRODUCTS,
)


def main() -> None:
    data = load_vendored()
    request = parse_url(AMM_URL)
    for policy in _POLICIES:
        spec = build_candidates(data, request, candidate_policies=(policy,)).candidates[0]
        families = generate_strip_families(spec)
        strips = plan_strips(spec)
        print(f"### policy={policy.value}")
        print("--- families ---")
        print("recipe_id,group_key,machines,flank_outputs,drain_outermost,machine_cap")
        for family in sorted(families, key=lambda f: (f.recipe_id, f.group_key)):
            print(
                f"{family.recipe_id},{family.group_key},"
                f"{family.total_machine_count},"
                f"{family.flank_outputs},"
                f"{getattr(family, 'drain_outermost', False)},"
                f"{getattr(family, 'machine_cap', 0)}"
            )
        print("--- strips ---")
        print("recipe_id,group_key,machines,flank_outputs,drain_outermost,box_height,in_above,in_below")
        for strip in sorted(strips, key=lambda s: (s.recipe_id, s.group_key)):
            print(
                f"{strip.recipe_id},{strip.group_key},"
                f"{strip.machines},"
                f"{strip.flank_outputs},"
                f"{getattr(strip, 'drain_outermost', False)},"
                f"{strip.box_height},"
                f"{len(strip.in_above)},{len(strip.in_below)}"
            )
        amm = [s for s in strips if s.recipe_id == "advanced-mining-machine"]
        print("--- advanced-mining-machine summary ---")
        print(f"amm_strips={len(amm)}")
        print(f"amm_flanked={sum(1 for s in amm if s.flank_outputs)}")
        print(f"amm_machines_total={sum(s.machines for s in amm)}")
        print(f"amm_box_height_total={sum(s.box_height for s in amm)}")
        print("--- whole spec ---")
        print(f"strips={len(strips)}")
        print(f"flanked_strips={sum(1 for s in strips if s.flank_outputs)}")
        print(f"total_box_height={sum(s.box_height for s in strips)}")
        print()


if __name__ == "__main__":
    main()
