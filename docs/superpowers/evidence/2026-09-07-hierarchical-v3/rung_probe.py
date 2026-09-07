"""Judge AND ROUTE every rung of the gap ladder, and record what each one said.

WHAT THIS WRAPS.  One thing: ``compose.pack_with_access``, replaced for the
duration of one ``flab2bp.cli.main`` call.  On the FIRST call the replacement
walks the same ``GAP_LADDER`` rungs ``pack_with_access`` itself would walk and,
for each rung, calls the same four internals in the same order and with the same
arguments the shipped function passes:

* ``compose._pack_at(placements, flows, spec, gap=rung, ramped=..., margin=...)``
* ``freeform._port_access_inventory(packing.nets).demands``
* ``compose._outer_ring(bounds)`` -- only when some demand's kind
  ``reaches_boundary``, exactly as ``pack_with_access`` gates it, which on a
  composed canvas is never
* ``compose._trunk_goals(packing, demands)``
* ``freeform._reserve_port_access(canvas, demands, boundary=..., bounds=...,
  cancelled=..., deadline=..., goals=goals)``

and then routes that rung's canvas with
``freeform._route_all(canvas, nets, belt_id, belt_model, bounds, deadline=...)``.
Afterwards it calls the REAL ``pack_with_access`` and returns its object, so the
build proceeds normally and the whole cell is one build.  Every rung after the
first call is passed straight through unprobed, because a strategy that
re-splits and composes again would otherwise pay for a second whole ladder.

WHAT IT DOES NOT CHANGE.  No ``src/`` file is touched, no constant is retuned,
and no wrapper alters an argument or a return value: ``pack_with_access``
receives the caller's own arguments and its own object is what compose gets
back.  The numbers below are READ off the shipped internals, not produced by
this script.  The ONE thing the probe does change about the build is its
CLOCK -- judging and routing six rungs costs wall, and that wall is taken out of
the composition's own deadline (see ``PROBE_SHARE``), so the cell's final
verdict is a probe artifact and is recorded but must not be read as a result.

WHY THE RAW GOAL-DRIVEN VERDICT IS RECORDED SEPARATELY FROM THE COMMITTED ONE.
``pack_with_access`` DISCARDS a trunk-goal reservation that assigned nothing at
all and re-asks the local-only question (``PackedCanvas.degraded``), because an
empty assignment stakes no corridors and is an unusable answer rather than a
geometric one.  This probe calls ``_reserve_port_access`` directly, so it sees
that discarded verdict -- which is the whole point of the measurement -- and it
records both:

* ``missing`` / ``missing_sealed`` / ``assigned`` are the RAW goal-driven
  answer, and ``wholesale`` is True when it assigned nothing while demands
  existed.  A wholesale answer is ``_match_access_corridors`` exhausting
  ``_ACCESS_CUT_ROUNDS`` and giving up, NOT a proof that the ground is sealed,
  and a table that cannot tell those apart cannot answer this task's question;
* ``routed`` / ``unrouted`` are measured after the SHIPPED rule has been
  applied -- the local-only re-ask when the goal-driven answer was unusable --
  so the routing column is comparable with what production would have on that
  rung's canvas.  Re-asking on the same canvas is exactly what
  ``pack_with_access`` does, and is sound because an empty assignment staked
  nothing to un-stake.

THE BUDGET IS A MEASUREMENT BUDGET AND NOT A GATE BUDGET.  The cell is run at
``--budget 180`` through the CLI's own flag -- there is deliberately no second
budget flag here, because two budgets that can disagree is a measurement nobody
can read.  180 s is not any gate's number and no gate clause may be read off
these runs.  Six rungs share ``PROBE_SHARE`` of the composition's remaining
wall, so each rung's ``_route_all`` runs on roughly a sixth of the clock a
single production composition would have had: on a cell whose router is
clock-bound, ``unrouted`` here is an UPPER bound, which is why
``unrouted_by_kind`` and ``unrouted_geometric`` are reported beside it and
``rung_deadline_s`` says how many seconds each rung actually had when it
started.  A rung whose ``route_status`` is ``STRANDED`` was NOT clock-bound --
``_route_all`` returns that only with no ``budget_exhausted`` and no
BUDGET-kind failure -- and its count is the router's real answer.  Note also
that ``route_iterations`` of 1 is not this clock: ``_route_all`` sets
``round_limit = 1`` at or above ``_SINGLE_ROUND_NETS = 64`` nets, which both
large cells are.  Unused clock flows FORWARD, so a cheap narrow rung funds a
wide one; a rung the share never reaches is recorded with ``judged: false``
rather than dropped.

WHERE THE PROBE IS STRICTER THAN PRODUCTION, DELIBERATELY.  ``RESERVE_SHARE``
is applied to EVERY rung here, whereas ``pack_with_access`` caps only rung 0
with ``RESERVE_WALL_SHARE`` and lets later rungs spend their whole ladder
slice.  A reader comparing the two must know this, even though it bound
nothing in the runs committed beside this file: reserve walls there were
0.45-4.17 s against caps of roughly 5-14 s, and no rung recorded
``verdict: timeout``.  It is spelled this way so that every rung is asked the
oracle on the same proportion of its own clock, which is what makes the rungs
comparable WITH EACH OTHER -- the comparison this measurement exists for.

    uv run python rung_probe.py <sidecar.json> -- <the exact flab2bp argv>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp import cli  # noqa: E402
from flab2bp.layout.freeform import (  # noqa: E402
    _port_access_inventory,
    _PreparationDeadline,
    _reserve_port_access,
    _route_all,
)
from flab2bp.layout.hierarchy import compose as compose_mod  # noqa: E402

#: The share of the composition's remaining wall the six-rung probe may spend.
#:
#: Not 1.0: the real ``pack_with_access`` still runs afterwards and is owed
#: enough clock to return an object rather than only ever raising
#: ``_PackingDeadline``.  Not much less either -- the rungs are the measurement.
PROBE_SHARE = 0.9

#: The share of ONE rung's slice its reservation may spend, mirroring
#: ``compose.RESERVE_WALL_SHARE`` so the oracle here is asked on the same
#: proportion of clock the shipped rung 0 gives it.
RESERVE_SHARE = compose_mod.RESERVE_WALL_SHARE

#: Router failure kinds that describe GROUND rather than clock.  Spelled out
#: rather than imported from ``route_feedback._GEOMETRIC_FAILURES`` because that
#: set excludes ``STATIC_ACCESS``, which for this question is still geometry.
_GEOMETRIC = frozenset(
    {"STATIC_ACCESS", "DYNAMIC_ACCESS", "SEALED_POCKET", "CONGESTION_WALL", "COMMIT_LINK"}
)


def _describe_missing(reservation, limit: int = 24) -> list[dict]:
    """One line per unserved demand: what it is and what the probe proved.

    ``frontier`` is the field the Lever C clause turns on: a non-empty frontier
    is an A* that expanded and stopped against ground, and an empty one is a
    demand nothing was proven about.
    """
    evidence = {item.demand: item for item in reservation.evidence}
    rows = []
    for demand in reservation.missing:
        found = evidence.get(demand)
        rows.append(
            {
                "item": demand.item,
                "belt": demand.belt,
                "kind": demand.kind.value,
                "columns": demand.columns,
                "frontier": 0 if found is None else len(found.frontier),
                "held": None if found is None else found.held,
                "wanted": None if found is None else found.wanted,
                "local_options": None if found is None else found.local_options,
                "reachable_options": None if found is None else found.reachable_options,
                "exhaustive": None if found is None else found.exhaustive,
            }
        )
    rows.sort(key=lambda row: (-row["frontier"], row["belt"], row["item"]))
    return rows[:limit]


def _sealed(reservation) -> int:
    """Missing demands whose evidence carries a non-empty frontier."""
    evidence = {item.demand: item for item in reservation.evidence}
    return sum(
        1
        for demand in reservation.missing
        if (found := evidence.get(demand)) is not None and found.frontier
    )


def _route_row(canvas, nets, spec, bounds, deadline: float | None) -> dict:
    """Route one rung's canvas and count what did not wire, by the router's word."""
    started = time.perf_counter()
    result = _route_all(
        canvas,
        nets,
        compose_mod._belt_id_for(spec),
        compose_mod._belt_model_for(spec),
        bounds,
        deadline=deadline,
    )
    wall = time.perf_counter() - started
    # The same accounting `compose.compose` does: a net that neither routed nor
    # failed is still an unwired cut, under the status that stopped the pass.
    accounted = set(result.routed) | {failure.net_id for failure in result.failures}
    kinds = Counter(failure.kind.name for failure in result.failures)
    unaccounted = sum(1 for net in nets if net.net_id is not None and net.net_id not in accounted)
    if unaccounted:
        kinds[result.status.name] += unaccounted
    return {
        "route_status": result.status.name,
        "routed": len(result.routed),
        "unrouted": len(result.failures) + unaccounted,
        "unrouted_by_kind": dict(sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))),
        "unrouted_geometric": sum(n for kind, n in kinds.items() if kind in _GEOMETRIC),
        "route_iterations": result.iterations,
        "route_wall_s": round(wall, 2),
    }


def _judge(
    placements, flows, spec, *, rung: int, ramped: bool, margin: int, deadline: float | None
) -> dict:
    """Pack, ask the goal-driven oracle, apply the shipped rule, and route."""
    started = time.perf_counter()
    packing = compose_mod._pack_at(placements, flows, spec, gap=rung, ramped=ramped, margin=margin)
    pack_wall = time.perf_counter() - started
    bounds = packing.canvas.limit
    assert bounds is not None  # `canvas_for` always sets it
    demands = _port_access_inventory(packing.nets).demands
    boundary = (
        compose_mod._outer_ring(bounds) if any(d.kind.reaches_boundary for d in demands) else None
    )
    goal_started = time.perf_counter()
    goals = compose_mod._trunk_goals(packing, demands)
    goals_wall = time.perf_counter() - goal_started

    row: dict = {
        "gap": rung,
        "judged": True,
        "demands": len(demands),
        "nets": len(packing.nets),
        "blocks": len(packing.blocks),
        "canvas": [bounds[2] - bounds[0] + 1, bounds[3] - bounds[1] + 1],
        "boundary_passed": boundary is not None,
        "goal_demands": len(goals),
        "goals_wall_s": round(goals_wall, 2),
        "pack_wall_s": round(pack_wall, 2),
        "rung_deadline_s": None if deadline is None else round(deadline - time.monotonic(), 2),
    }

    now = time.monotonic()
    reserve_deadline = (
        None if deadline is None else min(deadline, now + (deadline - now) * RESERVE_SHARE)
    )
    reserve_started = time.perf_counter()
    try:
        goal_driven = _reserve_port_access(
            packing.canvas,
            demands,
            boundary=boundary,
            bounds=bounds,
            cancelled=partial(compose_mod._spent, reserve_deadline),
            deadline=reserve_deadline,
            goals=goals,
        )
    except _PreparationDeadline:
        goal_driven = None
    row["reserve_wall_s"] = round(time.perf_counter() - reserve_started, 2)

    if goal_driven is None:
        row |= {
            "verdict": "timeout",
            "missing": None,
            "missing_sealed": None,
            "assigned": None,
            "complete": None,
            "wholesale": None,
            "missing_detail": [],
        }
    else:
        wholesale = not goal_driven.assigned and bool(demands)
        row |= {
            "verdict": (
                "complete" if goal_driven.complete else ("wholesale" if wholesale else "graded")
            ),
            "missing": len(goal_driven.missing),
            "missing_sealed": _sealed(goal_driven),
            "assigned": len(goal_driven.assigned),
            "complete": goal_driven.complete,
            "wholesale": wholesale,
            "evidence": len(goal_driven.evidence),
            "missing_detail": _describe_missing(goal_driven),
        }

    # THE SHIPPED RULE, applied here so the routing column is production-
    # comparable: a timeout or a wholesale give-up is re-asked local-only on
    # the rung's own clock, exactly as `pack_with_access` does, and it is that
    # reservation the canvas carries into `_route_all`.
    if goal_driven is not None and (goal_driven.assigned or not demands):
        committed, row["degraded"] = goal_driven, False
    else:
        row["degraded"] = True
        try:
            committed = _reserve_port_access(
                packing.canvas,
                demands,
                boundary=boundary,
                bounds=bounds,
                cancelled=partial(compose_mod._spent, deadline),
                deadline=deadline,
            )
        except _PreparationDeadline:
            committed = None
    row["committed_missing"] = None if committed is None else len(committed.missing)
    row["committed_assigned"] = None if committed is None else len(committed.assigned)

    if committed is None:
        row |= {
            "route_status": "NOT_RUN",
            "routed": None,
            "unrouted": None,
            "unrouted_by_kind": {},
            "unrouted_geometric": None,
            "route_wall_s": 0.0,
        }
    else:
        row |= _route_row(packing.canvas, packing.nets, spec, bounds, deadline)
    row["rung_wall_s"] = round(time.perf_counter() - started, 2)
    return row


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="rung_probe.py")
    ap.add_argument("sidecar", type=Path)
    ap.add_argument("--probe-share", type=float, default=PROBE_SHARE)
    if "--" not in argv[1:]:
        print(__doc__)
        return 2
    split = argv.index("--")
    args = ap.parse_args(argv[1:split])
    cell_argv = argv[split + 1 :]

    record: dict = {
        "argv": cell_argv,
        "probe_share": args.probe_share,
        "gap_ladder": list(compose_mod.GAP_LADDER),
        "reserve_share": float(RESERVE_SHARE),
    }
    rungs_out: list[dict] = []
    tail: list[dict] = []
    calls = [0]
    original_pack = compose_mod.pack_with_access

    def pack_spy(placements, flows, spec, *, ramped, deadline, margin, gap=compose_mod.MIN_GAP):
        calls[0] += 1
        if calls[0] > 1:
            return original_pack(
                placements, flows, spec, ramped=ramped, deadline=deadline, margin=margin, gap=gap
            )
        entered = time.monotonic()
        ladder = tuple(rung for rung in compose_mod.GAP_LADDER if rung >= gap) or (
            max(gap, compose_mod.MIN_GAP),
        )
        record["floor_gap"] = gap
        record["compose_wall_on_entry_s"] = (
            None if deadline is None else round(deadline - entered, 2)
        )
        probe_deadline = (
            None if deadline is None else entered + max(0.0, deadline - entered) * args.probe_share
        )
        for position, rung in enumerate(ladder):
            now = time.monotonic()
            if probe_deadline is not None and now >= probe_deadline:
                rungs_out.append({"gap": rung, "judged": False, "reason": "probe share spent"})
                continue
            # Unused clock flows FORWARD rather than being lost, so a cheap
            # narrow rung funds a wide one instead of the ladder stalling.
            share = (
                None
                if probe_deadline is None
                else now + (probe_deadline - now) / (len(ladder) - position)
            )
            try:
                rungs_out.append(
                    _judge(
                        placements,
                        flows,
                        spec,
                        rung=rung,
                        ramped=ramped,
                        margin=margin,
                        deadline=share,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - a crashed rung is a recorded rung
                rungs_out.append(
                    {"gap": rung, "judged": False, "reason": f"{type(exc).__name__}: {exc}"}
                )
            print(
                json.dumps({k: v for k, v in rungs_out[-1].items() if k != "missing_detail"}),
                flush=True,
            )
        try:
            packed = original_pack(
                placements, flows, spec, ramped=ramped, deadline=deadline, margin=margin, gap=gap
            )
        except BaseException as exc:
            tail.append({"raised": f"{type(exc).__name__}: {exc}"})
            raise
        tail.append(
            {
                "gap": packed.gap,
                "missing": len(packed.reservation.missing),
                "assigned": len(packed.reservation.assigned),
                "complete": packed.reservation.complete,
                "degraded": packed.degraded,
            }
        )
        return packed

    compose_mod.pack_with_access = pack_spy
    started = time.perf_counter()
    try:
        code = cli.main(cell_argv)
    except BaseException as exc:  # noqa: BLE001 - a crash is a recorded outcome
        record["crash"] = f"{type(exc).__name__}: {exc}"
        code = 70
    finally:
        compose_mod.pack_with_access = original_pack
    record |= {
        "wall_s": round(time.perf_counter() - started, 2),
        "exit": code,
        "pack_with_access_calls": calls[0],
        "rungs": rungs_out,
        "committed_tail": tail,
    }
    args.sidecar.write_text(json.dumps(record, indent=1, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
