"""Run ONE gate cell through the shipped CLI and dump what the CLI does not print.

``flab2bp.cli._report`` prints the area, the band, the belt facts and the
validation errors, but it never prints a single ``PlacementStats`` key, so v1's
gate could not have reported ``blocks`` / ``cut_lanes`` / ``strips_max`` even if
a cell had built (v1's did not: all five refused).  This gate has to report
them, plus Task 5's ``nogood_skips``, plus the gap rung Task 4's ladder
committed -- and ``PackedCanvas.gap`` never reaches ``PlacementStats`` at all.

So the cell runs through ``flab2bp.cli.main(argv)`` with **exactly the argv
v1's `run_large.sh` used** (plus the budget the gate names), and this wrapper
only READS what passes through, writing it to a JSON sidecar:

* ``pipeline.build``'s returned ``Build`` -- ``placement.stats``, area,
  buildings, the validator's errors bucketed by check;
* ``compose.pack_with_access`` -- the committed gap and the corridor
  reservation that chose it, once per composition attempt;
* ``strategy.allocate_cuts`` -- ``CutAllocation.player_fed``, the (block, item)
  pairs Task 1 leaves to the player.
* ``HierarchicalLayout._solve_round`` -- its return value is what ``lay_out``
  accumulates into ``stats["nogood_skips"]``, and ``stats`` is written only on
  the success path.  Every cell of this gate REFUSED, so Task 5's counter is
  unreachable through ``PlacementStats`` and this is the only way to report it.
  Added between round 1 and round 2, so it is present in the ``-r2`` sidecars
  only; both rounds' ``rounds``/``nogood_skips`` numbers are labelled as coming
  from here rather than from ``PlacementStats``.

NO PRODUCTION CODE IS CHANGED, and nothing here alters what the build does: the
wrappers call through and return the callee's own object.  Controller ruling R6
asks that ``player_fed`` be read off "whatever surface exists"; the answer is
that NEITHER ``PlacementStats`` NOR the ``-v`` log exposes it, and the number
this script records comes from this spy, which the gate labels as such.

The pipeline runs a serial attempt in-process (its only executor is a
``ThreadPoolExecutor`` over candidates, `pipeline.py:934`), so these wrappers
are in the same process as the composition.  The BLOCK solves are not -- they
run in ``hierarchy.strategy._spawn_pool`` -- which is fine, because nothing
here reads anything from inside a block solve.

    uv run python run_cell.py <sidecar.json> -- <the exact flab2bp argv>
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp import cli, pipeline  # noqa: E402
from flab2bp.layout.hierarchy import compose as compose_mod  # noqa: E402
from flab2bp.layout.hierarchy import strategy as strategy_mod  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[2] != "--":
        print(__doc__)
        return 2
    sidecar = Path(argv[1])
    cell_argv = argv[3:]

    record: dict = {"argv": cell_argv}
    packings: list[dict] = []
    allocations: list[dict] = []

    rounds: list[int] = []

    original_pack = compose_mod.pack_with_access
    original_allocate = strategy_mod.allocate_cuts
    original_build = pipeline.build
    original_round = strategy_mod.HierarchicalLayout._solve_round

    def round_spy(self, *args, **kwargs):
        skips = original_round(self, *args, **kwargs)
        rounds.append(int(skips))
        return skips

    def pack_spy(*args, **kwargs):
        packed = original_pack(*args, **kwargs)
        packings.append(
            {
                "gap": packed.gap,
                "reservation_complete": packed.reservation.complete,
                "reservation_assigned": len(packed.reservation.assigned),
                "reservation_missing": len(packed.reservation.missing),
            }
        )
        return packed

    def allocate_spy(*args, **kwargs):
        allocation = original_allocate(*args, **kwargs)
        allocations.append(
            {
                "flows": len(allocation.flows),
                "player_fed_pairs": len(allocation.player_fed),
                "player_fed": sorted(f"{b}:{item}" for b, item in allocation.player_fed),
            }
        )
        return allocation

    def build_spy(*args, **kwargs):
        built = original_build(*args, **kwargs)
        placement = built.placement
        record["build"] = {
            "strategy": built.strategy,
            "candidate": built.spec.label,
            "machines": built.spec.machine_count,
            "area": placement.area,
            "buildings": len(placement.buildings),
            "stats": {k: str(v) for k, v in dict(placement.stats).items()},
            "validation_errors": dict(Counter(f.check for f in built.report.errors)),
            "validation_error_count": len(built.report.errors),
            "refused_pairs": [str(r) for r in built.refused],
        }
        return built

    compose_mod.pack_with_access = pack_spy
    strategy_mod.allocate_cuts = allocate_spy
    strategy_mod.HierarchicalLayout._solve_round = round_spy
    pipeline.build = build_spy
    started = time.perf_counter()
    try:
        code = cli.main(cell_argv)
    except BaseException as exc:  # noqa: BLE001 - a crash is a recorded outcome
        record["crash"] = f"{type(exc).__name__}: {exc}"
        code = 70
    finally:
        compose_mod.pack_with_access = original_pack
        strategy_mod.allocate_cuts = original_allocate
        strategy_mod.HierarchicalLayout._solve_round = original_round
        pipeline.build = original_build
    record["wall_s"] = round(time.perf_counter() - started, 2)
    record["exit"] = code
    record["packings"] = packings
    record["allocations"] = allocations
    record["rounds"] = len(rounds)
    record["nogood_skips_per_round"] = rounds
    record["nogood_skips"] = sum(rounds)
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
