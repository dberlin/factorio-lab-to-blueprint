"""Is the CP-SAT phase earning its keep?

Three configurations on the same real-URL spec:

* **greedy**  -- the fallback construction alone (``time_budget_s=0``), no solver.
* **gap 10%** -- CP-SAT told to stop once it is within 10% of its own bound,
  rather than burning the rest of the budget proving optimality nobody collects.
* **full**    -- CP-SAT with the whole budget, the current behaviour.

The question this answers: area measured against budget plateaus almost
immediately (1484 / 1435 / 1470 / 1435 / 1476 tiles at 0.1 / 0.5 / 1 / 2 / 4
seconds), so the solver is not slow at *finding* its answer, only at *proving*
it. If greedy lands close, the CP-SAT phase could be replaced by a heuristic at
roughly 100x the speed. Strategy A's equivalent gap is known and large -- 3850
fallback versus 2805 solved, so its solver is worth 27% -- but freeform's has
never been measured.

    uv run python scripts/gap_vs_greedy.py
    uv run python scripts/gap_vs_greedy.py --url-id magnetic-coil --repeat 3

Multi-worker CP-SAT is nondeterministic, so ``--repeat`` reports median and
range; a single sample is noise, and comparing two runs that landed on different
packings has already produced one wrong conclusion in this project.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from ortools.sat.python import cp_model  # noqa: E402

from flab2bp.bench.corpus import URL_CORPUS  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout.freeform import FreeformLayout  # noqa: E402
from flab2bp.layout.spine import SpineLayout  # noqa: E402
from flab2bp.rates.candidates import build_candidates  # noqa: E402


def install_gap(limit: float | None) -> None:
    """Force ``relative_gap_limit`` on every solve, or restore the default."""
    real = getattr(cp_model.CpSolver, "_flab_real_solve", None)
    if real is None:
        real = cp_model.CpSolver.solve
        cp_model.CpSolver._flab_real_solve = real  # type: ignore[attr-defined]

    def probed(self: Any, model: Any, *a: Any, **kw: Any) -> Any:
        if limit is not None:
            self.parameters.relative_gap_limit = limit
        return real(self, model, *a, **kw)

    cp_model.CpSolver.solve = probed  # type: ignore[method-assign]


def measure(cls: Any, spec: Any, budget: float, repeat: int) -> tuple[int, str, float, int]:
    areas, walls, belts = [], [], []
    for _ in range(repeat):
        t = time.time()
        p = cls(power=False).lay_out(spec, time_budget_s=budget)
        walls.append(time.time() - t)
        areas.append(p.area)
        belts.append(int(p.stats.get("belt_tiles", 0)))
    rng = f"{min(areas)}-{max(areas)}" if len(set(areas)) > 1 else ""
    return int(statistics.median(areas)), rng, statistics.median(walls), int(
        statistics.median(belts)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url-id", default=None, help="corpus url_id; default = first small entry")
    ap.add_argument("--budget", type=float, default=2.0)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--gap", type=float, default=0.10)
    args = ap.parse_args()

    entry = next(
        (e for e in URL_CORPUS if e.url_id == args.url_id),
        None,
    ) or max(URL_CORPUS, key=lambda e: e.machines if e.machines < 200 else 0)
    print(f"spec: {entry.url_id}  (~{entry.machines} machines)\n{entry.url}\n")

    ds = load_vendored()
    specs = build_candidates(ds, parse_url(entry.url), count=3)
    spec = min(specs.candidates, key=lambda s: s.machine_count)
    print(f"candidate: {spec.label!r}  {spec.machine_count} machines, {len(spec.groups)} groups")
    print(f"budget={args.budget}s  repeat={args.repeat}  gap={args.gap:.0%}\n")

    hdr = f"{'strategy':<10}{'config':<12}{'area':>8}{'range':>12}{'belts':>8}{'wall':>8}"
    print(hdr)
    print("-" * len(hdr))

    for name, cls in (("spine", SpineLayout), ("freeform", FreeformLayout)):
        rows = []
        install_gap(None)
        rows.append(("greedy", *measure(cls, spec, 0.0, 1)))
        install_gap(args.gap)
        rows.append((f"gap {args.gap:.0%}", *measure(cls, spec, args.budget, args.repeat)))
        install_gap(None)
        rows.append(("full", *measure(cls, spec, args.budget, args.repeat)))

        base = rows[-1][1]
        for cfg, area, rng, wall, belts in rows:
            delta = f"  ({area / base - 1:+.1%} vs full)" if base else ""
            print(f"{name:<10}{cfg:<12}{area:>8}{rng:>12}{belts:>8}{wall:>7.2f}s{delta}")
        print()

    install_gap(None)
    print(
        "If greedy is within a few percent of full, the CP-SAT phase is buying\n"
        "little and a heuristic packer would be far faster. If gap-10% matches\n"
        "full at a fraction of the wall time, the budget is being spent proving\n"
        "a bound nothing reads."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
