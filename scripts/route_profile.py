"""Where does a routing pass actually go?

    uv run python scripts/route_profile.py universe-matrix --budget 4
    uv run python scripts/route_profile.py quantum-chip --cprofile

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
import json
import pstats
import sys
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import Protocol, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flab2bp.bench.corpus import URL_CORPUS  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import (  # noqa: E402
    finalize,
    freeform,
    global_router,
    last_mile,
    route_kernel,
    sequence_solver,
    strip_variants,
    validate,
)
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import NoValidLayout, Placement  # noqa: E402
from flab2bp.layout.route_feedback import Cell, DetailedRouteResult  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402
from flab2bp.spec import BuildSpec  # noqa: E402


class _Layout(Protocol):
    def lay_out(
        self, spec: BuildSpec, *, time_budget_s: float = 15.0
    ) -> Placement: ...


class _Strategy(Protocol):
    def __call__(self, *, workers: int) -> _Layout: ...


class _HeightRow(TypedDict):
    height: int
    width: int
    failed: str | int | None
    route_s: float | None


def _strategy(name: str) -> _Strategy:
    if name == "freeform":

        def freeform_layout(*, workers: int) -> freeform.FreeformLayout:
            return freeform.FreeformLayout(
                band_policy=BandPolicy("portable"),
                workers=workers,
            )

        return freeform_layout
    from flab2bp.layout.sequence_solver import SequencePairLayout

    def sequence_pair(*, workers: int) -> SequencePairLayout:
        del workers
        return SequencePairLayout(
            band_policy=BandPolicy("portable"),
        )

    return sequence_pair


def _spec(url_id: str, candidate_policy: CandidatePolicy) -> BuildSpec:
    entry = next(e for e in URL_CORPUS if e.url_id == url_id)
    return build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=(candidate_policy,),
    ).candidates[0]


PHASES = (
    "plan_strips", "strip_families", "prepare", "place_coaters", "coater_frame_bans",
    "junction_ban", "power_plan", "static_risks", "relaxed_search", "last_mile",
    "finalize", "validate",
)


_LAST_MILE_KEYS = (
    "last_mile_invocations",
    "last_mile_solved",
    "last_mile_proved",
    "last_mile_bounded",
    "last_mile_commit_rejected",
    "last_mile_restore_mismatch",
    "last_mile_relation_skipped_siblings",
    "last_mile_nodes",
    "last_mile_expansions",
    "last_mile_seconds",
    "last_mile_relation_strips",
)


def _last_mile_row(stats: Mapping[str, object]) -> dict[str, float]:
    """The last-mile counters, if this run produced any.

    `scripts/audit.py` rows carry no `stats` object, so this is the ONLY path
    by which these numbers reach a gate record.  An empty dict here means the
    run never entered the pass, which is a fact worth printing rather than a
    zero worth inventing.
    """
    return {
        key: float(str(stats[key])) for key in _LAST_MILE_KEYS if key in stats
    }


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
        #: Seconds per `_prepare_routing_problem` call, in call order, so a
        #: cold first candidate and a warm second one are both visible.
        self.prepare_calls: list[float] = []

    def add(self, key: str, dt: float) -> None:
        self.t[key] = self.t.get(key, 0.0) + dt
        self.n[key] = self.n.get(key, 0) + 1


def install(tally: Tally) -> Callable[[], None]:
    """Patch the module's routing entry points with timing shims."""
    orig_astar = freeform._astar
    orig_route_all = freeform._route_all
    orig_commit = freeform._commit_paths
    orig_make_grid = freeform._make_grid
    orig_refresh = freeform._Grid.refresh_history
    orig_landmarks = freeform._Grid.build_landmarks
    orig_reserve = freeform._reserve_port_access
    orig_merge = freeform._merge_frontier
    orig_last_mile = last_mile.solve_cluster

    def astar(
        canvas: freeform._Canvas,
        starts: list[Cell],
        goals: set[Cell],
        history: dict[Cell, float],
        pressure: float,
        bounds: tuple[int, int, int, int],
        budget: dict[str, int] | None = None,
        deadline: float | None = None,
        blame: dict[Cell, float] | None = None,
        grid: freeform._Grid | None = None,
        owned_starts: Collection[Cell] = (),
        released_starts: Collection[Cell] = (),
        forbidden: Collection[Cell] = (),
        blocking_owners: Mapping[Cell, int] | None = None,
    ) -> freeform._PathSearchResult:
        t0 = time.perf_counter()
        out = orig_astar(
            canvas,
            starts,
            goals,
            history,
            pressure,
            bounds,
            budget,
            deadline,
            blame,
            grid,
            owned_starts,
            released_starts,
            forbidden,
            blocking_owners,
        )
        dt = time.perf_counter() - t0
        tally.add("astar", dt)
        tally.expansions += out.expansions
        if out.path is None:
            tally.astar_none += 1
        else:
            tally.astar_hit += 1
            tally.path_cells += len(out.path)
        tally.calls.append(
            (out.expansions, dt, -1 if out.path is None else len(out.path))
        )
        return out

    def route_all(
        canvas: freeform._Canvas,
        nets: list[freeform._Net],
        belt_id: int,
        belt_model: int,
        bounds: tuple[int, int, int, int],
        deadline: float | None = None,
        budget: dict[str, int] | None = None,
        planned_power_sites: Sequence[tuple[int, int]] | None = None,
        junction_frame_bans: Sequence[frozenset[Cell]] = (),
        *,
        prioritize_source_families: bool = False,
    ) -> DetailedRouteResult:
        t0 = time.perf_counter()
        out = orig_route_all(
            canvas,
            nets,
            belt_id,
            belt_model,
            bounds,
            deadline,
            budget,
            planned_power_sites,
            junction_frame_bans,
            prioritize_source_families=prioritize_source_families,
        )
        tally.add("route_all", time.perf_counter() - t0)
        tally.passes += 1
        tally.rounds += out.iterations
        return out

    def commit(
        canvas: freeform._Canvas,
        nets: list[freeform._Net],
        paths: Mapping[int, Sequence[Cell]],
        belt_id: int,
        belt_model: int,
        src_group: Mapping[int, tuple[int, ...]] | None = None,
        dst_group: Mapping[int, tuple[int, ...]] | None = None,
        *,
        source_hints: Mapping[int, Cell] | None = None,
        sink_hints: Mapping[int, Cell] | None = None,
        failure_details: dict[int, freeform._CommitFailure] | None = None,
    ) -> tuple[int, ...]:
        t0 = time.perf_counter()
        out = orig_commit(
            canvas,
            nets,
            paths,
            belt_id,
            belt_model,
            src_group,
            dst_group,
            source_hints=source_hints,
            sink_hints=sink_hints,
            failure_details=failure_details,
        )
        tally.add("commit_paths", time.perf_counter() - t0)
        return out

    def make_grid(
        canvas: freeform._Canvas,
        box: tuple[int, int, int, int],
        span: tuple[int, int, int, int],
        history: Mapping[Cell, float],
    ) -> freeform._Grid:
        t0 = time.perf_counter()
        out = orig_make_grid(canvas, box, span, history)
        tally.add("make_grid", time.perf_counter() - t0)
        return out

    def refresh(self: freeform._Grid, history: Mapping[Cell, float]) -> None:
        t0 = time.perf_counter()
        orig_refresh(self, history)
        tally.add("refresh_history", time.perf_counter() - t0)

    def landmarks(self: freeform._Grid, count: int) -> None:
        t0 = time.perf_counter()
        orig_landmarks(self, count)
        tally.add("build_landmarks", time.perf_counter() - t0)

    def reserve(
        canvas: freeform._Canvas,
        nets: list[freeform._Net],
        *,
        twice: Collection[Cell] = (),
        failed_ports: set[Cell] | None = None,
        demands: dict[Cell, tuple[int, int, int]] | None = None,
    ) -> int:
        t0 = time.perf_counter()
        out = orig_reserve(
            canvas, nets, twice=twice, failed_ports=failed_ports, demands=demands
        )
        tally.add("reserve_port_access", time.perf_counter() - t0)
        return out

    def merge(
        canvas: freeform._Canvas,
        paths: Mapping[int, Sequence[Cell]],
        siblings: tuple[int, ...],
        junctionable: Callable[[int, int, int], bool] | None = None,
        *,
        provenance: dict[Cell, Cell] | None = None,
        belt_prefab: tuple[int, int] | None = None,
        tentative_ok: bool = False,
        owned_guard: Mapping[Cell, Cell] | None = None,
    ) -> set[Cell]:
        t0 = time.perf_counter()
        out = orig_merge(
            canvas,
            paths,
            siblings,
            junctionable,
            provenance=provenance,
            belt_prefab=belt_prefab,
            tentative_ok=tentative_ok,
            owned_guard=owned_guard,
        )
        tally.add("merge_frontier", time.perf_counter() - t0)
        return out

    def timed_last_mile(
        problem: last_mile.ClusterProblem,
        environment: last_mile.ClusterEnvironment,
    ) -> last_mile.ClusterResult:
        t0 = time.perf_counter()
        try:
            return orig_last_mile(problem, environment)
        finally:
            tally.add("last_mile", time.perf_counter() - t0)

    def timed(key: str, sites: Sequence[tuple[object, str]]) -> Callable[[], None]:
        """Patch every ``(module, attribute)`` binding site with one shared shim.

        A function reimported by name (``from ... import x``) is bound
        separately in each importer's module namespace, so patching only its
        defining module misses calls made through the other binding -- as
        `sequence_solver` does for `_prepare_routing_problem`, `plan_strips`
        and `generate_strip_families`.  Every site shares one shim and one
        tally entry per call, however the caller reached it.
        """
        originals = [getattr(module, target) for module, target in sites]
        original = originals[0]

        def shim(*args: object, **kwargs: object) -> object:
            t0 = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                dt = time.perf_counter() - t0
                tally.add(key, dt)
                if key == "prepare":
                    tally.prepare_calls.append(dt)

        for module, target in sites:
            setattr(module, target, shim)

        def undo() -> None:
            for (module, target), orig in zip(sites, originals, strict=True):
                setattr(module, target, orig)

        return undo

    phase_undo = [
        timed("prepare", [
            (freeform, "_prepare_routing_problem"),
            (sequence_solver, "_prepare_routing_problem"),
        ]),
        timed("place_coaters", [(freeform, "_place_coaters")]),
        timed("coater_frame_bans", [
            (freeform, "_projected_coater_junction_bans_by_frame"),
        ]),
        timed("junction_ban", [(freeform, "_prepared_junction_ban")]),
        timed("power_plan", [(freeform, "_power_plan")]),
        timed("static_risks", [
            (freeform, "_staged_static_relation_projection_risks_uncached"),
        ]),
        timed("plan_strips", [
            (freeform, "plan_strips"),
            (sequence_solver, "plan_strips"),
        ]),
        timed("strip_families", [
            (strip_variants, "generate_strip_families"),
            (sequence_solver, "generate_strip_families"),
        ]),
        timed("relaxed_search", [(global_router, "_search_relaxed")]),
        timed("finalize", [(finalize, "finalize_placement")]),
        timed("validate", [(validate, "validate")]),
    ]

    freeform._astar = astar
    freeform._route_all = route_all
    freeform._commit_paths = commit
    freeform._make_grid = make_grid
    type.__setattr__(freeform._Grid, "refresh_history", refresh)
    type.__setattr__(freeform._Grid, "build_landmarks", landmarks)
    freeform._reserve_port_access = reserve
    freeform._merge_frontier = merge
    last_mile.solve_cluster = timed_last_mile

    def restore() -> None:
        freeform._astar = orig_astar
        freeform._route_all = orig_route_all
        freeform._commit_paths = orig_commit
        freeform._make_grid = orig_make_grid
        type.__setattr__(freeform._Grid, "refresh_history", orig_refresh)
        type.__setattr__(freeform._Grid, "build_landmarks", orig_landmarks)
        freeform._reserve_port_access = orig_reserve
        freeform._merge_frontier = orig_merge
        last_mile.solve_cluster = orig_last_mile
        for undo in phase_undo:
            undo()

    return restore


def heights(
    url_id: str,
    candidate_policy: CandidatePolicy,
    workers: int,
    ceiling: float,
    strategy: str = "freeform",
) -> int:
    """What would EVERY candidate height do, given a clock it cannot spend?

    The sweep tries heights in order and stops at the deadline, so a refusal
    reads "one pass, one height" and says nothing about the four it never
    reached.  This runs the same sweep with a ceiling far past what the router
    can spend and prints the outcome of each height in the order the sweep
    takes them -- which is the measurement that decides whether routing heights
    IN PARALLEL would convert a refusal or merely reach more failures sooner.
    """
    spec = _spec(url_id, candidate_policy)
    orig_build = freeform._build
    seen: list[_HeightRow] = []

    # INSTRUMENTED AT `_build` AND NOT AT `_pack`, because the two sweeps do not
    # share a packer: `seqpair._sweep` runs its own arrangement search and never
    # calls `_pack` at all.  Every sweep does hand `_build` a `_Pack`, and that
    # carries the height and the width, so one shim covers both strategies.
    def build(
        spec: BuildSpec,
        strips: list[freeform.Strip],
        pack: freeform._Pack,
        *,
        power: bool,
        route: bool,
        policy: BandPolicy,
        ramped: bool = False,
        deadline: float | None = None,
        budget: dict[str, int] | None = None,
        staged_static_cache: freeform._StagedStaticCache | None = None,
    ) -> freeform._BuildResult:
        t0 = time.perf_counter()
        row = _HeightRow(
            height=pack.height,
            width=pack.width,
            failed=None,
            route_s=None,
        )
        seen.append(row)
        try:
            out = orig_build(
                spec,
                strips,
                pack,
                power=power,
                route=route,
                policy=policy,
                ramped=ramped,
                deadline=deadline,
                budget=budget,
                staged_static_cache=staged_static_cache,
            )
        except Exception as exc:  # noqa: BLE001
            row["failed"] = type(exc).__name__
            row["route_s"] = time.perf_counter() - t0
            raise
        row["failed"] = out.routing.failed_count
        row["route_s"] = time.perf_counter() - t0
        return out

    freeform._build = build
    t0 = time.perf_counter()
    verdict = "OK"
    try:
        _strategy(strategy)(workers=workers).lay_out(spec, time_budget_s=ceiling)
    except NoValidLayout as exc:
        verdict = f"REFUSED: {exc.reason[:80]}"
    finally:
        freeform._build = orig_build
    print(
        f"=== {url_id} ceiling={ceiling}s  {time.perf_counter() - t0:.1f}s  {verdict}"
    )
    for i, row in enumerate(seen):
        print(f"  #{i:<2} height {row['height']:>5}  w={str(row['width']):>5}  "
              f"route {-1.0 if row['route_s'] is None else row['route_s']:6.1f}s "
              f" failed {row['failed']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url_id")
    ap.add_argument("--budget", type=float, default=4.0)
    ap.add_argument(
        "--candidate-policy",
        type=CandidatePolicy,
        choices=tuple(CandidatePolicy),
        default=CandidatePolicy.NO_PROLIFERATOR,
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--cprofile", action="store_true")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--heights", action="store_true")
    ap.add_argument("--strategy", default="freeform")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.heights:
        return heights(
            args.url_id,
            args.candidate_policy,
            args.workers,
            args.budget,
            args.strategy,
        )

    spec = _spec(args.url_id, args.candidate_policy)
    for run in range(args.repeat):
        tally = Tally()
        restore = install(tally)
        prof = cProfile.Profile() if args.cprofile else None
        t0 = time.perf_counter()
        verdict = "OK"
        placement = None
        try:
            if prof is not None:
                prof.enable()
            placement = _strategy(args.strategy)(workers=args.workers).lay_out(
                spec, time_budget_s=args.budget
            )
        except NoValidLayout as exc:
            verdict = f"REFUSED: {exc.reason[:90]}"
        finally:
            if prof is not None:
                prof.disable()
            restore()
        wall = time.perf_counter() - t0
        routing = tally.t.get("route_all", 0.0)
        inner = tally.t.get("astar", 0.0)
        if args.json:
            print(json.dumps({
                "url_id": args.url_id,
                "strategy": args.strategy,
                "power": True,
                "budget_s": args.budget,
                "run": run + 1,
                "repeat": args.repeat,
                "verdict": verdict,
                "wall_s": wall,
                "route_all_s": routing,
                "astar_s": inner,
                "astar_routing_share": inner / max(routing, 1e-9),
                "astar_wall_share": inner / max(wall, 1e-9),
                "expansions": tally.expansions,
                "hits": tally.astar_hit,
                "misses": tally.astar_none,
                "phases": {
                    key: {"s": tally.t[key], "n": tally.n[key]}
                    for key in PHASES
                    if key in tally.t
                },
                "prepare_calls_s": list(tally.prepare_calls),
                "route_backend": route_kernel.selected_backend(),
                "last_mile_stats": (
                    {} if placement is None else _last_mile_row(placement.stats)
                ),
            }, separators=(",", ":"), sort_keys=True))
            continue

        print(
            f"=== {args.url_id} budget={args.budget} run {run + 1}/{args.repeat}"
        )
        print(f"    {verdict}")
        print(f"    wall {wall:.2f}s   routing passes {tally.passes}   "
              f"rip-up rounds {tally.rounds}")
        print(f"    _route_all total {routing:.2f}s ({100 * routing / wall:.0f}% of wall)")
        for key in ("astar", "commit_paths", "make_grid", "refresh_history",
                    "build_landmarks", "reserve_port_access", "merge_frontier"):
            if key in tally.t:
                print(f"      {key:<22} {tally.t[key]:7.2f}s  "
                      f"n={tally.n[key]:<7} "
                      f"{100 * tally.t[key] / max(routing, 1e-9):5.1f}% of routing")
        other = routing - sum(
            tally.t.get(k, 0.0)
            for k in ("astar", "commit_paths", "make_grid", "refresh_history",
                      "build_landmarks", "reserve_port_access")
        )
        print(f"      {'(route_all itself)':<22} {other:7.2f}s  "
              f"{100 * other / max(routing, 1e-9):5.1f}% of routing")
        for key in PHASES:
            if key in tally.t:
                print(f"      {key:<22} {tally.t[key]:7.2f}s  n={tally.n[key]:<7} "
                      f"{100 * tally.t[key] / max(wall, 1e-9):5.1f}% of wall")
        if tally.prepare_calls:
            print("      prepare per call: " + ", ".join(f"{s:.2f}" for s in tally.prepare_calls))
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
