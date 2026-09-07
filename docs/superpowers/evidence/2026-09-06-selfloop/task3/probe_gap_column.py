"""Does a flanked gap belt cross a south INPUT lane once the drain moves out?

`_flank_lane` runs one belt per machine down column ``m.x + pw - 1`` from the
machine's east pose to the output lane.  With the drain innermost that column
crosses nothing.  With the drain OUTERMOST it must cross every south input lane
row -- unless the lane's belt run has already ended west of that column.

Prints, per strip length, the machines whose gap column is inside a south input
lane's belt run.  Empty means the drain can move without a belt collision.
"""

from __future__ import annotations

from fractions import Fraction as F

from flab2bp.layout.freeform import plan_strips
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
    for count in (2, 6):
        spec = six_input_spec(count)
        for strip_len in (1, 2, 3, 6):
            strips = plan_strips(spec, strip_len=strip_len)
            for s in strips:
                if not s.flank_outputs:
                    continue
                needs = [(lane, s.input_lane_tiles(lane)) for lane in s.in_below]
                gaps = [k * s.pw + s.pw - 1 for k in range(s.machines)]
                crossing = [
                    (gx, lane[0], need) for gx in gaps for lane, need in needs if gx < need
                ]
                print(
                    f"count={count} strip_len={strip_len} machines={s.machines} pw={s.pw} "
                    f"mw={s.mw} width={s.width} box_height={s.box_height} "
                    f"drain_outermost={s.drain_outermost} "
                    f"drain_row={s.row_of_output(0)} "
                    f"below_rows={[s.row_of_input(lane[0]) for lane in s.in_below]}"
                )
                print(f"  gap columns {gaps}")
                print(f"  south lane tiles {[(lane[0], need) for lane, need in needs]}")
                print(f"  crossings {len(crossing)}: {crossing[:4]}")
                break


if __name__ == "__main__":
    main()
