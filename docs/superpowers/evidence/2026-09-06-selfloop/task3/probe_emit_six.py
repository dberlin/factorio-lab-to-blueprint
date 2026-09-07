"""Emit the six-ingredient Matrix Lab spec and write a decodable blueprint.

NOT the corpus build (that one refused; see build-um.log).  This is the same
spec `tests/layout/test_freeform.py::six_input_spec` uses -- a real
`universe-matrix` recipe on real Matrix Labs -- laid out in process so the
decode probe can show each lab's six single-item input runs.
"""

from __future__ import annotations

import sys
from fractions import Fraction as F
from pathlib import Path

from flab2bp.dsp.codec import encode
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.freeform import FreeformLayout, plan_strips
from flab2bp.spec import BuildSpec, MachineGroup

INGREDIENTS = (
    "antimatter",
    "electromagnetic-matrix",
    "energy-matrix",
    "gravity-matrix",
    "information-matrix",
    "structure-matrix",
)


def six_input_spec(count: int = 2) -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="universe-matrix",
                machine_item_id="matrix-lab",
                count=count,
                inputs_per_machine={i: F(1) for i in INGREDIENTS},
                outputs_per_machine={"universe-matrix": F(1)},
            ),
        ),
        external_inputs={i: F(count) for i in INGREDIENTS},
        outputs={"universe-matrix": F(count)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=F(30),
        label="six-input",
    )


def main() -> None:
    out = Path(sys.argv[1])
    spec = six_input_spec()
    for strip in plan_strips(spec, strip_len=6):
        print(
            f"strip {strip.group_key} machines={strip.machines} box_height={strip.box_height} "
            f"width={strip.width} flank={strip.flank_outputs} "
            f"drain_outermost={strip.drain_outermost}"
        )
        print(f"  in_above {strip.in_above}")
        print(f"  in_below {strip.in_below}")
        drain = strip.row_of_output(0)
        print(f"  drain row {drain} span {strip.sorter_span(drain)}")
        for lane in strip.in_below:
            row = strip.row_of_input(lane[0])
            print(f"  below {lane} row {row} span {strip.sorter_span(row)}")
    placement = FreeformLayout(band_policy=BandPolicy("portable")).lay_out(spec, time_budget_s=2.0)
    out.write_text(encode(placement))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
