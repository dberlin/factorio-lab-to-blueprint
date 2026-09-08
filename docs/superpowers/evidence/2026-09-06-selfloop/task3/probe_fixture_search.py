"""Find a flanked strip whose drain did NOT have to move, with single-item lanes.

`test_a_flanked_strip_that_never_needed_the_row_is_unchanged` needs a fixture
that survives spec §9 R1's collapse of the mixing ladder: flanked (so the drain
row map is exercised), every lane one item (so the ban cannot refuse it), and
`len(in_below) < below_cap` (so `drain_outermost` is False and the
pre-2026-09-07 row map is what is pinned).

Sweeps every catalog building that a strip can be planned on, for two to six
ingredients, and reports the pairs that satisfy all three.
"""

from __future__ import annotations

import string
from fractions import Fraction as F

from flab2bp.dsp import catalog
from flab2bp.layout.freeform import _side_lane_caps
from flab2bp.layout.strip_variants import _logical_strip_plans
from flab2bp.spec import BuildSpec, MachineGroup


def spec_for(machine: str, n: int) -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="impossible",
                machine_item_id=machine,
                count=1,
                inputs_per_machine={k: F(1) for k in string.ascii_lowercase[:n]},
                outputs_per_machine={"out": F(1)},
            ),
        )
    )


def main() -> None:
    names = sorted(catalog._item_ids())  # noqa: SLF001 - probe
    hits = 0
    for machine in names:
        for n in range(2, 7):
            try:
                plans = _logical_strip_plans(spec_for(machine, n))
            except Exception:  # noqa: BLE001 - a probe; unplannable is the common case
                continue
            for plan in plans:
                if not plan.flank_outputs:
                    continue
                lanes = (*plan.in_above, *plan.in_below)
                if not all(len(lane) == 1 for lane in lanes):
                    continue
                item_id = plan.item_id
                building = catalog.building(item_id)
                caps = _side_lane_caps(item_id, 0.0, building.height)
                print(
                    f"{machine:<34} n={n} above={len(plan.in_above)} "
                    f"below={len(plan.in_below)} caps={caps} "
                    f"drain_outermost={plan.drain_outermost} "
                    f"single_item=True"
                )
                hits += 1
    print(f"total flanked single-item plans: {hits}")


if __name__ == "__main__":
    main()
