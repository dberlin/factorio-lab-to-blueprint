"""Replay real A* searches, so the inner loop can be A/B'd without CP-SAT.

    uv run python scripts/route_bench.py --capture universe-matrix
    uv run python scripts/route_bench.py --cases /tmp/route-cases-universe-matrix.pkl

WHY A REPLAY AND NOT A CELL RUN

A whole-cell A/B measures the router through CP-SAT, which is multi-worker and
nondeterministic, so two runs route DIFFERENT packs and the seconds are not
comparable.  Capturing the real arguments of real searches and replaying them
gives the opposite: the same work every time, to the node, so a 3% change is
visible -- and the paths come back as objects that can be compared cell for
cell against the ones the captured run committed.

THE CORRECTNESS CHECK IS THE POINT.  ``--check`` prints a digest over every
path returned.  A candidate that changes the digest has changed which belt gets
laid, whatever it did to the clock, and is a different router rather than a
faster one.

WHAT IS CAPTURED, AND WHAT IS SHARED

Only what a search MUTATES is copied: ``canvas.blocked`` (staked paths),
``canvas.routing_ports`` (rebound per net) and the grid's ``occ`` and ``hist``.
Everything else -- ``solid``, ``keep_out``, the landmark fields, ``base`` -- is
read-only for the length of a routing pass, so sharing it keeps a capture of
sixty searches to megabytes rather than gigabytes.  ``_astar`` itself writes to
nothing except the ``blame`` and ``budget`` the caller hands it, and the bench
hands it fresh ones.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import pickle
import sys
import time
from collections.abc import Collection, Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from flab2bp.bench.corpus import URL_CORPUS  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import freeform, last_mile  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402


def _snapshot(
    canvas: freeform._Canvas,
    grid: freeform._Grid | None,
    history: dict[tuple[int, int, int], float],
) -> tuple[
    freeform._Canvas,
    freeform._Grid | None,
    dict[tuple[int, int, int], float],
]:
    """The parts a routing pass moves, copied; the rest shared."""
    shot_canvas = copy.copy(canvas)
    shot_canvas.blocked = dict(canvas.blocked)
    # `_reserve_port_access` rewrites this between routing passes, and
    # `_Canvas.free` reads it for every start cell -- sharing it replayed one
    # capture in eighty against the WRONG reservations and moved its path by a
    # cell, which is exactly the size of error this bench exists to see.
    shot_canvas.reserved = dict(canvas.reserved)
    shot_canvas.solid = set(canvas.solid)
    shot_canvas.keep_out = set(canvas.keep_out)
    # `_Canvas.free` reads these two as well, and BOTH grow after a capture --
    # junction guards are staked as later nets are routed.  Sharing them replayed
    # a `universe-matrix` capture with a start cell the live pass had guarded in
    # the meantime: the search dropped that start, took a longer path, and the
    # replay digest differed from the capture for a reason that had nothing to do
    # with the router.
    shot_canvas.guard = set(canvas.guard)
    shot_canvas.belt_ban = dict(canvas.belt_ban)
    shot_canvas.routing_ports = canvas.routing_ports
    shot_grid = None
    if grid is not None:
        shot_grid = replace(
            grid,
            occ=bytearray(grid.occ),
            hist=None if grid.hist is None else list(grid.hist),
        )
    return shot_canvas, shot_grid, dict(history)


def capture(
    url_id: str,
    budget: float,
    every: int,
    cap: int,
    out: Path,
    policy: CandidatePolicy = CandidatePolicy.NO_PROLIFERATOR,
) -> None:
    entry = next(e for e in URL_CORPUS if e.url_id == url_id)
    spec = build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=(policy,),
    ).candidates[0]

    orig = freeform._astar
    cases: list[dict[str, Any]] = []
    seen = 0

    def spy(
        canvas: freeform._Canvas,
        starts: list[tuple[int, int, int]],
        goals: set[tuple[int, int, int]],
        history: dict[tuple[int, int, int], float],
        pressure: float,
        bounds: tuple[int, int, int, int],
        budget: dict[str, int] | None = None,
        deadline: float | None = None,
        blame: dict[tuple[int, int, int], float] | None = None,
        grid: freeform._Grid | None = None,
        owned_starts: Collection[tuple[int, int, int]] = (),
        released_starts: Collection[tuple[int, int, int]] = (),
        forbidden: Collection[tuple[int, int, int]] = (),
        blocking_owners: Mapping[tuple[int, int, int], int] | None = None,
    ) -> freeform._PathSearchResult:
        nonlocal seen
        want = seen % every == 0 and len(cases) < cap
        if want:
            shot_canvas, shot_grid, shot_hist = _snapshot(canvas, grid, history)
        seen += 1
        out_path = orig(
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
        if want:
            cases.append(
                {
                    "canvas": shot_canvas,
                    "grid": shot_grid,
                    "history": shot_hist,
                    "starts": list(starts),
                    "goals": set(goals),
                    "pressure": pressure,
                    "bounds": bounds,
                    "owned_starts": tuple(owned_starts),
                    "released_starts": tuple(released_starts),
                    "forbidden": tuple(forbidden),
                    "blocking_owners": (None if blocking_owners is None else dict(blocking_owners)),
                    "path": out_path,
                }
            )
        return out_path

    freeform._astar = spy
    try:
        freeform.FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=1,
        ).lay_out(spec, time_budget_s=budget)
    except NoValidLayout:
        pass
    finally:
        freeform._astar = orig
    out.write_bytes(pickle.dumps(cases, protocol=5))
    # `_astar` returns a `_PathSearchResult`, whose `path` is the tuple of cells.
    lens = [0 if c["path"].path is None else len(c["path"].path) for c in cases]
    print(
        f"captured {len(cases)} of {seen} searches -> {out} "
        f"({out.stat().st_size / 1e6:.1f} MB); "
        f"{sum(1 for n in lens if n)} found, "
        f"{sum(lens):,} path cells"
    )


def capture_clusters(
    url_id: str,
    budget: float,
    cap: int,
    out: Path,
    policy: CandidatePolicy = CandidatePolicy.NO_PROLIFERATOR,
) -> None:
    """Snapshot every last-mile invocation of one real cell run.

    The hook is `last_mile.CAPTURE` rather than `_astar`, because the stranded
    state Phase B cares about only exists at the moment `_route_all` would give
    up, and that is the one call that sees it.
    """
    entry = next(e for e in URL_CORPUS if e.url_id == url_id)
    spec = build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=(policy,),
    ).candidates[0]

    cases: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def sink(shot: last_mile.ClusterCapture) -> None:
        if len(cases) + len(pending) >= cap:
            return
        canvas = cast(freeform._Canvas, shot.canvas)
        grid = cast(freeform._Grid, shot.grid)
        shot_canvas, shot_grid, shot_hist = _snapshot(canvas, grid, dict(shot.history))
        pending.append(
            {
                "kind": "cluster",
                "run": shot.run,
                "canvas": shot_canvas,
                "grid": shot_grid,
                "history": shot_hist,
                "problem": shot.problem,
                "ends": {
                    index: (list(starts), set(goals), ports)
                    for index, (starts, goals, ports) in shot.ends.items()
                },
                "pressure": shot.pressure,
                "bounds": shot.bounds,
                "budget_left": shot.budget_left,
                "budget_floor": shot.budget_floor,
                "deadline_remaining": shot.deadline_remaining,
                "owned_starts": dict(shot.owned_starts),
                "rejected": dict(shot.rejected),
                "blocking_owners": dict(shot.blocking_owners),
            }
        )

    orig_solve = last_mile.solve_cluster

    def spy(
        problem: last_mile.ClusterProblem,
        environment: last_mile.ClusterEnvironment,
    ) -> last_mile.ClusterResult:
        result = orig_solve(problem, environment)
        # `CAPTURE` fires before the solve, so the pending shot is this one's.
        while pending:
            shot = pending.pop(0)
            shot["result"] = result
            cases.append(shot)
        return result

    last_mile.CAPTURE = sink
    last_mile.solve_cluster = spy
    try:
        freeform.FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=1,
        ).lay_out(spec, time_budget_s=budget)
    except NoValidLayout:
        pass
    finally:
        last_mile.CAPTURE = None
        last_mile.solve_cluster = orig_solve
    out.write_bytes(pickle.dumps(cases, protocol=5))
    outcomes = [case["result"].outcome.value for case in cases]
    bounds_hit = [case["result"].bound.value for case in cases]
    print(
        f"captured {len(cases)} cluster searches -> {out} "
        f"({out.stat().st_size / 1e6:.1f} MB); "
        + ", ".join(f"{value}={outcomes.count(value)}" for value in sorted(set(outcomes)))
        + "; bounds "
        + ", ".join(
            f"{value or 'none'}={bounds_hit.count(value)}" for value in sorted(set(bounds_hit))
        )
    )


def digest(paths: Iterable[Any]) -> str:
    hasher = hashlib.sha256()
    for p in paths:
        hasher.update(b"-" if p is None else repr(p).encode())
    return hasher.hexdigest()[:16]


def bench(path: Path, rounds: int, check: bool, landmarks: int | None) -> int:
    cases = pickle.loads(path.read_bytes())
    if landmarks is not None:
        # RE-SWEEP THE LANDMARKS ON THE CAPTURED GRID, so the strength of the
        # heuristic can be varied over the SAME searches.  `base` is the
        # occupancy the real pass built its fields from, and the sweep is
        # deterministic, so `--landmarks 4` reproduces the capture exactly --
        # which is the control this experiment needs.
        # `alt_flat` is `alt` concatenated for the compiled loop and the two must
        # move together; restoring only `alt` would hand the kernel a band count
        # its buffer cannot cover.
        done: dict[int, tuple[tuple[Any, ...], Any]] = {}
        for case in cases:
            grid = case["grid"]
            if grid is None:
                continue
            key = id(grid.base)
            if key not in done:
                grid.alt = ()
                grid.build_landmarks(landmarks)
                done[key] = (grid.alt, grid.alt_flat)
            grid.alt, grid.alt_flat = done[key]
        print(f"landmarks re-swept to {landmarks} on {len(done)} grid(s)")
    best = None
    for r in range(rounds):
        # A fresh budget per round, sized so it can never bind: the point is to
        # replay the SAME work, not to re-impose a cap the capture already had.
        budget = {"left": 1 << 40}
        got: list[Any] = []
        t0 = time.perf_counter()
        for case in cases:
            canvas = case["canvas"]
            canvas.routing_ports = canvas.routing_ports
            got.append(
                freeform._astar(
                    canvas,
                    case["starts"],
                    case["goals"],
                    case["history"],
                    case["pressure"],
                    case["bounds"],
                    budget,
                    None,
                    {},
                    case["grid"],
                    case.get("owned_starts", ()),
                    case.get("released_starts", ()),
                    case.get("forbidden", ()),
                    case.get("blocking_owners"),
                )
            )
        dt = time.perf_counter() - t0
        spent = (1 << 40) - budget["left"]
        if best is None or dt < best[0]:
            best = (dt, spent, got)
        print(
            f"  round {r + 1}: {dt:.3f}s  {spent:,} expansions  "
            f"{1e6 * dt / max(spent, 1):.3f} us/exp"
        )
    if best is None:
        raise ValueError("rounds must be positive")
    dt, spent, got = best
    print(
        f"BEST {dt:.3f}s  {spent:,} expansions  "
        f"{1e6 * dt / max(spent, 1):.3f} us/exp  digest {digest(got)}"
    )
    if check:
        want = digest(case["path"] for case in cases)
        same = digest(got)
        print(
            f"captured digest {want}   replay digest {same}   "
            f"{'MATCH' if want == same else 'DIFFER'}"
        )
        return 0 if want == same else 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture")
    ap.add_argument("--budget", type=float, default=4.0)
    ap.add_argument("--every", type=int, default=8)
    ap.add_argument("--cap", type=int, default=64)
    ap.add_argument("--cases", type=Path)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--landmarks", type=int)
    ap.add_argument("--stranded", action="store_true")
    ap.add_argument(
        "--policy",
        type=CandidatePolicy,
        choices=tuple(CandidatePolicy),
        default=CandidatePolicy.NO_PROLIFERATOR,
    )
    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    if args.capture:
        out = args.cases or Path(f"/tmp/route-cases-{args.capture}-{args.policy.value}.pkl")
        if args.stranded:
            capture_clusters(args.capture, args.budget, args.cap, out, args.policy)
        else:
            capture(args.capture, args.budget, args.every, args.cap, out, args.policy)
        return 0
    if not args.cases:
        ap.error("--cases or --capture required")
    return bench(args.cases, args.rounds, args.check, args.landmarks)


if __name__ == "__main__":
    raise SystemExit(main())
