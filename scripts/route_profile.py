"""Where does a routing pass actually go?

    uv run python scripts/route_profile.py universe-matrix --power 1 --budget 4
    uv run python scripts/route_profile.py quantum-chip --power 1 --cprofile

Two instruments, deliberately, because each lies in a way the other does not:

* ``--cprofile`` attributes wall time to functions, and inflates every Python
  call it observes -- which in an A* inner loop is most of the work.  Its
  numbers are RATIOS, not seconds.
* the default is a wrapper-based tally: it patches ``_route_all``, ``_astar``,
  ``_commit_paths``, ``_make_grid`` and ``_Grid.refresh_history`` with timing
  shims and counts calls, expansions (from the shared budget's decrements) and
  rip-up rounds.  A shim per call is nothing against a search; the inner loop
  is untouched, so the seconds are real.

Nothing here changes what the router does.  The wrappers are installed on the
module object and the deadline is the caller's, so the run under measurement is
the run the audit makes.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flab2bp.bench.corpus import URL_CORPUS  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import freeform  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.rates.candidates import build_candidates  # noqa: E402


def _strategy(name: str):
    if name == "freeform":
        return freeform.FreeformLayout
    from flab2bp.layout.seqpair import SeqPairLayout

    return SeqPairLayout


def _spec(url_id: str, index: int):
    entry = next(e for e in URL_CORPUS if e.url_id == url_id)
    cands = build_candidates(load_vendored(), parse_url(entry.url), count=4).candidates
    return cands[index]


class Tally:
    """Wall time and counts per routing phase, one run."""

    def __init__(self) -> None:
        self.t: dict[str, float] = {}
        self.n: dict[str, int] = {}
        self.expansions = 0
        self.rounds = 0
        self.passes = 0
        self.astar_none = 0
        self.astar_hit = 0
        self.path_cells = 0
        #: One row per search: (expansions, seconds, path length or -1).
        self.calls: list[tuple[int, float, int]] = []

    def add(self, key: str, dt: float) -> None:
        self.t[key] = self.t.get(key, 0.0) + dt
        self.n[key] = self.n.get(key, 0) + 1


def install(tally: Tally):
    """Patch the module's routing entry points with timing shims."""
    orig_astar = freeform._astar
    orig_route_all = freeform._route_all
    orig_commit = freeform._commit_paths
    orig_make_grid = freeform._make_grid
    orig_refresh = freeform._Grid.refresh_history
    orig_landmarks = freeform._Grid.build_landmarks
    orig_reserve = freeform._reserve_port_access
    orig_merge = freeform._merge_frontier

    def astar(canvas, starts, goals, history, pressure, bounds, budget=None,
              deadline=None, blame=None, grid=None):
        before = budget["left"] if budget is not None else 0
        t0 = time.perf_counter()
        out = orig_astar(canvas, starts, goals, history, pressure, bounds,
                         budget, deadline, blame, grid)
        dt = time.perf_counter() - t0
        tally.add("astar", dt)
        spent = (before - budget["left"]) if budget is not None else 0
        tally.expansions += spent
        if out is None:
            tally.astar_none += 1
        else:
            tally.astar_hit += 1
            tally.path_cells += len(out)
        tally.calls.append((spent, dt, -1 if out is None else len(out)))
        return out

    def route_all(canvas, nets, belt_id, belt_model, bounds, deadline=None,
                  budget=None):
        t0 = time.perf_counter()
        out = orig_route_all(canvas, nets, belt_id, belt_model, bounds,
                             deadline, budget)
        tally.add("route_all", time.perf_counter() - t0)
        tally.passes += 1
        tally.rounds += out[2]
        return out

    def commit(*a, **k):
        t0 = time.perf_counter()
        out = orig_commit(*a, **k)
        tally.add("commit_paths", time.perf_counter() - t0)
        return out

    def make_grid(*a, **k):
        t0 = time.perf_counter()
        out = orig_make_grid(*a, **k)
        tally.add("make_grid", time.perf_counter() - t0)
        return out

    def refresh(self, history):
        t0 = time.perf_counter()
        out = orig_refresh(self, history)
        tally.add("refresh_history", time.perf_counter() - t0)
        return out

    def landmarks(self, count):
        t0 = time.perf_counter()
        out = orig_landmarks(self, count)
        tally.add("build_landmarks", time.perf_counter() - t0)
        return out

    def reserve(*a, **k):
        t0 = time.perf_counter()
        out = orig_reserve(*a, **k)
        tally.add("reserve_port_access", time.perf_counter() - t0)
        return out

    def merge(*a, **k):
        t0 = time.perf_counter()
        out = orig_merge(*a, **k)
        tally.add("merge_frontier", time.perf_counter() - t0)
        return out

    freeform._astar = astar
    freeform._route_all = route_all
    freeform._commit_paths = commit
    freeform._make_grid = make_grid
    freeform._Grid.refresh_history = refresh
    freeform._Grid.build_landmarks = landmarks
    freeform._reserve_port_access = reserve
    freeform._merge_frontier = merge

    def restore() -> None:
        freeform._astar = orig_astar
        freeform._route_all = orig_route_all
        freeform._commit_paths = orig_commit
        freeform._make_grid = orig_make_grid
        freeform._Grid.refresh_history = orig_refresh
        freeform._Grid.build_landmarks = orig_landmarks
        freeform._reserve_port_access = orig_reserve
        freeform._merge_frontier = orig_merge

    return restore


def heights(url_id: str, power: int, spec_index: int, workers: int,
            ceiling: float, strategy: str = "freeform") -> int:
    """What would EVERY candidate height do, given a clock it cannot spend?

    The sweep tries heights in order and stops at the deadline, so a refusal
    reads "one pass, one height" and says nothing about the four it never
    reached.  This runs the same sweep with a ceiling far past what the router
    can spend and prints the outcome of each height in the order the sweep
    takes them -- which is the measurement that decides whether routing heights
    IN PARALLEL would convert a refusal or merely reach more failures sooner.
    """
    spec = _spec(url_id, spec_index)
    orig_build = freeform._build
    seen: list[dict] = []

    # INSTRUMENTED AT `_build` AND NOT AT `_pack`, because the two sweeps do not
    # share a packer: `seqpair._sweep` runs its own arrangement search and never
    # calls `_pack` at all.  Every sweep does hand `_build` a `_Pack`, and that
    # carries the height and the width, so one shim covers both strategies.
    def build(spec_, strips_, pack_, **kw):
        t0 = time.perf_counter()
        row = {"height": pack_.height, "width": pack_.width,
               "failed": None, "route_s": None}
        seen.append(row)
        try:
            out = orig_build(spec_, strips_, pack_, **kw)
        except Exception as exc:  # noqa: BLE001
            row["failed"] = type(exc).__name__
            row["route_s"] = time.perf_counter() - t0
            raise
        row["failed"] = out[1]
        row["route_s"] = time.perf_counter() - t0
        return out

    freeform._build = build
    t0 = time.perf_counter()
    verdict = "OK"
    try:
        _strategy(strategy)(power=power, workers=workers).lay_out(
            spec, time_budget_s=ceiling
        )
    except NoValidLayout as exc:
        verdict = f"REFUSED: {exc.reason[:80]}"
    finally:
        freeform._build = orig_build
    print(f"=== {url_id} power={power} ceiling={ceiling}s  "
          f"{time.perf_counter() - t0:.1f}s  {verdict}")
    for i, row in enumerate(seen):
        print(f"  #{i:<2} height {row['height']:>5}  w={str(row['width']):>5}  "
              f"route {-1.0 if row['route_s'] is None else row['route_s']:6.1f}s "
              f" failed {row['failed']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url_id")
    ap.add_argument("--power", type=int, default=1)
    ap.add_argument("--budget", type=float, default=4.0)
    ap.add_argument("--spec-index", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--cprofile", action="store_true")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--heights", action="store_true")
    ap.add_argument("--strategy", default="freeform")
    args = ap.parse_args()

    if args.heights:
        return heights(args.url_id, args.power, args.spec_index,
                       args.workers, args.budget, args.strategy)

    spec = _spec(args.url_id, args.spec_index)
    for run in range(args.repeat):
        tally = Tally()
        restore = install(tally)
        prof = cProfile.Profile() if args.cprofile else None
        t0 = time.perf_counter()
        verdict = "OK"
        try:
            if prof is not None:
                prof.enable()
            freeform.FreeformLayout(power=args.power, workers=args.workers).lay_out(
                spec, time_budget_s=args.budget
            )
        except NoValidLayout as exc:
            verdict = f"REFUSED: {exc.reason[:90]}"
        finally:
            if prof is not None:
                prof.disable()
            restore()
        wall = time.perf_counter() - t0

        print(f"=== {args.url_id} power={args.power} budget={args.budget} "
              f"run {run + 1}/{args.repeat}")
        print(f"    {verdict}")
        print(f"    wall {wall:.2f}s   routing passes {tally.passes}   "
              f"rip-up rounds {tally.rounds}")
        routing = tally.t.get("route_all", 0.0)
        print(f"    _route_all total {routing:.2f}s ({100 * routing / wall:.0f}% of wall)")
        for key in ("astar", "commit_paths", "make_grid", "refresh_history",
                    "build_landmarks", "reserve_port_access", "merge_frontier"):
            if key in tally.t:
                print(f"      {key:<22} {tally.t[key]:7.2f}s  "
                      f"n={tally.n[key]:<7} "
                      f"{100 * tally.t[key] / max(routing, 1e-9):5.1f}% of routing")
        inner = tally.t.get("astar", 0.0)
        other = routing - sum(
            tally.t.get(k, 0.0)
            for k in ("astar", "commit_paths", "make_grid", "refresh_history",
                      "build_landmarks", "reserve_port_access")
        )
        print(f"      {'(route_all itself)':<22} {other:7.2f}s  "
              f"{100 * other / max(routing, 1e-9):5.1f}% of routing")
        print(f"    A*: {tally.astar_hit} found / {tally.astar_none} none, "
              f"{tally.expansions:,} expansions, "
              f"{tally.path_cells:,} path cells")
        if tally.expansions:
            print(f"    {tally.expansions / max(inner, 1e-9):,.0f} expansions/s, "
                  f"{1e6 * inner / tally.expansions:.2f} us/expansion")
        # WHERE THE EXPANSIONS GO -- a search that finds nothing still spends
        # them, and a cap-sized failure spends `_MAX_EXPANSIONS` of them.
        found = [c for c in tally.calls if c[2] >= 0]
        missed = [c for c in tally.calls if c[2] < 0]
        for name, rows in (("found", found), ("none ", missed)):
            if not rows:
                continue
            exp = sum(r[0] for r in rows)
            sec = sum(r[1] for r in rows)
            print(f"      {name}: n={len(rows):<5} {exp:>10,} exp "
                  f"({100 * exp / max(tally.expansions, 1):4.1f}%)  {sec:6.2f}s "
                  f"({100 * sec / max(inner, 1e-9):4.1f}%)")
        if found:
            ratio = sorted(r[0] / max(r[2], 1) for r in found)
            exps = sorted(r[0] for r in found)
            mid = len(found) // 2
            print(f"      found: median {exps[mid]:,} exp, p90 "
                  f"{exps[int(0.9 * len(exps))]:,}, max {exps[-1]:,}; "
                  f"median exp/cell {ratio[mid]:.1f}")
        top = sorted(tally.calls, key=lambda r: -r[0])[:10]
        print("      ten dearest searches (exp, s, len): "
              + ", ".join(f"({e:,},{s:.2f},{n})" for e, s, n in top))
        if prof is not None:
            buf = io.StringIO()
            pstats.Stats(prof, stream=buf).sort_stats("tottime").print_stats(25)
            print(buf.getvalue())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
