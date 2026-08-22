"""Stream CP-SAT's search progress for a single layout solve.

Answers: how big is the model, how long does it take to *build*, and how fast
does the solver close the gap once it starts?

The strategies pin ``num_search_workers = 1`` internally for bake-off
determinism.  This probe overrides that at solve time -- after the module has
set its own parameters -- so the override actually wins.

    uv run python scripts/solve_probe.py --strategy spine    --workers 8 --budget 10
    uv run python scripts/solve_probe.py --strategy freeform --workers 8 --budget 10
    uv run python scripts/solve_probe.py --strategy freeform --dump-model

``--dump-model`` reports variable/constraint counts without solving.  Look at
that first if the process eats tens of GB: that is model *construction* blowing
up, and no time budget can bound it.
"""

from __future__ import annotations

import argparse
import faulthandler
import os
import resource
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from ortools.sat.python import cp_model  # noqa: E402


def _rss_gb() -> float:
    """Peak RSS in GB. macOS reports bytes, Linux kilobytes."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / 1e9 if sys.platform == "darwin" else raw / 1e6


def _call_any(obj: Any, *names: str, default: Any = None) -> Any:
    """First of ``names`` that exists on ``obj``, called if callable.

    ortools renamed its CamelCase API to snake_case; which spelling exists
    depends on the version, so never bind to just one.
    """
    for name in names:
        attr = getattr(obj, name, None)
        if attr is None:
            continue
        try:
            return attr() if callable(attr) else attr
        except Exception:  # noqa: BLE001 - diagnostics must not break the probe
            continue
    return default


def _model_size(model: Any) -> tuple[int, int]:
    proto = _call_any(model, "Proto", "proto", default=None)
    if proto is None:
        return (0, 0)
    return (len(proto.variables), len(proto.constraints))


def install_probe(
    *, workers: int, budget: float, log: bool, dump_only: bool
) -> list[dict[str, float]]:
    """Patch every CpSolver solve entry point to report size and force params."""
    solves: list[dict[str, float]] = []

    # Patch exactly ONE entry point. ortools keeps the CamelCase name as an
    # alias that delegates to the snake_case one, so wrapping both double-counts
    # every solve and prints each line twice.
    names = [n for n in ("solve", "Solve") if hasattr(cp_model.CpSolver, n)][:1]
    if not names:
        raise RuntimeError("CpSolver exposes neither Solve nor solve")

    def make_probe(real: Callable[..., Any]) -> Callable[..., Any]:
        def probed(self: Any, model: Any, *a: Any, **kw: Any) -> Any:
            n_vars, n_cons = _model_size(model)

            self.parameters.num_search_workers = workers
            self.parameters.max_time_in_seconds = budget
            self.parameters.log_search_progress = log
            self.parameters.log_to_stdout = log

            idx = len(solves) + 1
            print(
                f"\n=== solve #{idx}: {n_vars:,} vars  {n_cons:,} constraints  "
                f"workers={workers}  budget={budget}s ===",
                flush=True,
            )
            if dump_only:
                solves.append({"vars": n_vars, "constraints": n_cons, "wall": 0.0})
                return cp_model.UNKNOWN

            t0 = time.time()
            status = real(self, model, *a, **kw)
            wall = time.time() - t0

            solved = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            obj = _call_any(self, "ObjectiveValue", "objective_value") if solved else None
            bound = (
                _call_any(self, "BestObjectiveBound", "best_objective_bound") if solved else None
            )
            print(
                f"--- solve #{idx}: {_call_any(self, 'StatusName', 'status_name', default=status)}"
                f"  obj={obj}  bound={bound}  wall={wall:.2f}s",
                flush=True,
            )
            solves.append({"vars": n_vars, "constraints": n_cons, "wall": wall})
            # Return the status object untouched -- newer ortools hands back an
            # enum whose .name callers rely on, so casting to int breaks them.
            return status

        return probed

    for name in names:
        setattr(cp_model.CpSolver, name, make_probe(getattr(cp_model.CpSolver, name)))
    return solves


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strategy", choices=("spine", "freeform"), default="spine")
    ap.add_argument(
        "--workers", type=int, default=8, help="num_search_workers (0 = let CP-SAT choose)"
    )
    ap.add_argument("--budget", type=float, default=10.0, help="per-solve seconds")
    ap.add_argument("--total-budget", type=float, default=None, help="budget handed to lay_out()")
    # Power ON by default, matching the pipeline. It was off, which made
    # `towers: 0` in the stats look like a bug rather than the setting.
    ap.add_argument("--no-power", dest="power", action="store_false")
    ap.add_argument("--no-log", dest="log", action="store_false", help="suppress CP-SAT's log")
    ap.add_argument("--dump-model", action="store_true", help="report size without solving")
    ap.add_argument(
        "--watchdog",
        type=float,
        default=0.0,
        help="dump a stack trace every N seconds -- names the line a hang is spinning on",
    )
    ap.add_argument(
        "--hard-kill",
        type=float,
        default=0.0,
        help="abort with a traceback after N seconds total",
    )
    args = ap.parse_args()

    # Only ONE faulthandler timer can be armed -- a second call cancels the
    # first -- so the periodic dump owns it and the hard kill runs on a thread.
    if args.watchdog:
        # repeat=True keeps dumping, so you can see whether it is stuck on one
        # line or grinding a loop that never terminates.
        faulthandler.dump_traceback_later(args.watchdog, repeat=True, exit=False)

    if args.hard_kill:

        def _kill() -> None:
            time.sleep(args.hard_kill)
            print(f"\n!!! hard kill after {args.hard_kill}s -- final stack:\n", flush=True)
            faulthandler.dump_traceback()
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(2)

        threading.Thread(target=_kill, daemon=True, name="hard-kill").start()

    solves = install_probe(
        workers=args.workers, budget=args.budget, log=args.log, dump_only=args.dump_model
    )

    from tests.layout.test_spine import magnetic_ring_spec

    spec = magnetic_ring_spec()
    print(
        f"spec: {sum(g.count for g in spec.groups)} machines, {len(spec.groups)} groups",
        flush=True,
    )

    strategy: Any
    if args.strategy == "spine":
        from flab2bp.layout.spine import SpineLayout

        strategy = SpineLayout(power=args.power)
    else:
        from flab2bp.layout.freeform import FreeformLayout

        strategy = FreeformLayout(power=args.power)

    t0 = time.time()
    placement = strategy.lay_out(spec, time_budget_s=args.total_budget or args.budget)
    wall = time.time() - t0
    solve_wall = sum(s["wall"] for s in solves)

    print(f"\n{'=' * 70}")
    print(f"strategy      : {args.strategy} (power={args.power})")
    print(f"area          : {placement.area}")
    print(f"total wall    : {wall:.2f}s")
    print(f"  in solver   : {solve_wall:.2f}s  ({len(solves)} solves)")
    print(f"  in build/py : {wall - solve_wall:.2f}s   <-- no time budget bounds this")
    print(f"peak RSS      : {_rss_gb():.2f} GB")
    if solves:
        biggest = max(solves, key=lambda s: s["vars"])
        print(
            f"largest model : {biggest['vars']:,.0f} vars  "
            f"{biggest['constraints']:,.0f} constraints"
        )
    print(f"stats         : {placement.stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
