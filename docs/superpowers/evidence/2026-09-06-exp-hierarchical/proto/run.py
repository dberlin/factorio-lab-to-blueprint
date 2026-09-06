"""Hierarchical block-decomposition spike driver.

    uv run python docs/superpowers/evidence/2026-09-06-exp-hierarchical/proto/run.py <label>

``<label>`` is one of ``belt3``, ``zurl2``, ``mall``, ``mall-no-proliferator``.

Pipeline: whole ``BuildSpec`` -> rate-weighted partition -> one sub-``BuildSpec``
per block -> the existing placers, two blocks at a time -> translate onto one
canvas -> corridor-route the inter-block cuts -> ``finalize`` -> ``validate`` ->
``codec.encode``.  Everything is judged against a spec re-derived from what was
actually built, never against the original counts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compose as compose_mod  # noqa: E402
import partition as partition_mod  # noqa: E402
import pressure as pressure_mod  # noqa: E402
import specs as specs_mod  # noqa: E402

from flab2bp.dsp import codec  # noqa: E402
from flab2bp.layout import finalize, markers, validate  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import NoValidLayout, Placement, PlacementCompletion  # noqa: E402
from flab2bp.pipeline import _id_map, _new_layout  # noqa: E402
from flab2bp.spec import BuildSpec  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "out"

CASES = {
    "belt3": ("belt3", "all-products", 12408),
    "zurl2": ("zurl2", "all-products", 40905),
    "mall": ("mall", "all-products", None),
    "mall-no-proliferator": ("mall", "no-proliferator", None),
}


def _cache_key(sub: BuildSpec, budget: float) -> str:
    payload = json.dumps(
        {
            "groups": sorted((g.recipe_id, g.count, str(g.proliferator_mode)) for g in sub.groups),
            "ext": sorted((k, str(v)) for k, v in sub.external_inputs.items()),
            "out": sorted((k, str(v)) for k, v in sub.outputs.items()),
            "spray": sorted((k, v) for k, v in sub.spray_lanes.items()),
            "budget": budget,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _uptime() -> str:
    try:
        return subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()
    except OSError:  # pragma: no cover
        return "?"


def _solve_block(
    args: tuple[BuildSpec, str, float, bool, int],
) -> tuple[dict[str, object], Placement | None]:
    spec, strategy, budget, vertical, islands = args
    started = time.monotonic()
    layout = _new_layout(
        strategy,  # type: ignore[arg-type]
        belt_vertical_construction=vertical,
        sequence_islands=islands,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
    )
    try:
        placement = layout.lay_out(spec, time_budget_s=budget)
    except NoValidLayout as exc:
        return (
            {
                "strategy": strategy,
                "wall_s": round(time.monotonic() - started, 2),
                "verdict": f"REFUSED: {exc.reason}"[:400],
                "ok": False,
            },
            None,
        )
    except Exception as exc:  # noqa: BLE001 - a placer CRASH is a result, not an abort
        # `mall/all-products` block 3 crashed both the run and, before this,
        # the experiment: `ValueError: stage-boundary transform must rebuild
        # every restart identically`.  A crash in one block must not lose the
        # other nine, and it is itself evidence about the sub-specs a
        # decomposer hands the placers.
        return (
            {
                "strategy": strategy,
                "wall_s": round(time.monotonic() - started, 2),
                "verdict": f"CRASH: {type(exc).__name__}: {exc}"[:400],
                "ok": False,
                "crash": True,
            },
            None,
        )
    return (
        {
            "strategy": strategy,
            "wall_s": round(time.monotonic() - started, 2),
            "verdict": "OK",
            "ok": True,
            "area": placement.area,
            "strips": float(placement.stats.get("strips", 0) or 0),
            "buildings": len(placement.buildings),
        },
        placement,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("label", choices=sorted(CASES))
    ap.add_argument("--cap", type=int, default=120, help="machines per block")
    ap.add_argument("--budget", type=float, default=15.0, help="seconds per block per strategy")
    ap.add_argument("--gap", type=int, default=6, help="tiles between blocks")
    ap.add_argument("--parallel", type=int, default=2, help="blocks solved at once")
    ap.add_argument("--max-depth", type=int, default=3, help="escalation rounds")
    ap.add_argument("--cache", action="store_true", help="reuse solved blocks across runs")
    ap.add_argument("--no-route", action="store_true", help="compose without any corridor belts")
    ap.add_argument(
        "--arm",
        choices=("size-cap", "depth-pressure"),
        default="size-cap",
        help=(
            "size-cap: agglomerative merge under --cap. "
            "depth-pressure: level the DAG, cut at the local minima of the "
            "depth pressure profile, and keep each high-pressure region "
            "together however large it is."
        ),
    )
    ap.add_argument(
        "--single-row",
        action="store_true",
        help="anchor every block at y=0 so each keeps the latitude rows it was certified at",
    )
    args = ap.parse_args()

    url_label, policy, best_known = CASES[args.label]
    out_label = args.label
    if args.arm != "size-cap":
        out_label = f"{out_label}-{args.arm}"
    if args.no_route:
        out_label = f"{out_label}-blocks-only"
    OUT.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "label": out_label,
        "routing": "none (blocks only)" if args.no_route else "corridor router",
        "url": url_label,
        "policy": policy,
        "cap": args.cap,
        "budget_s": args.budget,
        "gap": args.gap,
        "best_known_area": best_known,
        "uptime_start": _uptime(),
    }
    total_started = time.monotonic()

    loaded = specs_mod.load(url_label, policy)
    spec = loaded.spec
    record["machines"] = spec.machine_count
    record["groups"] = len(spec.groups)

    # --- partition ----------------------------------------------------------
    t0 = time.monotonic()
    if args.arm == "depth-pressure":
        seed_blocks, cut_depths, profile = pressure_mod.depth_pressure_blocks(spec)
        order, seed_cuts = partition_mod.derive_cuts(seed_blocks)
        part = partition_mod.Partition(blocks=[seed_blocks[i] for i in order], cuts=seed_cuts)
        record["depth_cut_after"] = cut_depths
        record["depth_pressure_profile"] = profile
    else:
        part = partition_mod.partition(spec, cap=args.cap, max_repairs=0)
        record["depth_pressure_profile"] = pressure_mod.depth_profile(spec)
    record["arm"] = args.arm
    record["partition_wall_s"] = round(time.monotonic() - t0, 3)

    #: One entry per block: its units, its solved placement, its arm records,
    #: and the cap it was cut at.  Escalation replaces a refusing entry with its
    #: children, which is the hierarchy actually recursing.
    entries: list[dict[str, object]] = [
        {"units": block, "placement": None, "arms": [], "cap": args.cap, "depth": 0}
        for block in part.blocks
    ]

    # A block's solve depends only on its own sub-spec, so a cache lets the
    # composition half be iterated without paying for the placers again.  The
    # reported block wall is always the wall of a COLD run.
    cache_path = OUT / f".cache-{args.label}-{args.cap}-{args.budget:g}.pkl"
    cache: dict[str, list[tuple[dict[str, object], Placement | None]]] | None = None
    if args.cache:
        cache = pickle.loads(cache_path.read_bytes()) if cache_path.exists() else {}

    solve_wall = 0.0
    rounds: list[dict[str, object]] = []
    cuts: list[tuple[str, int, int, Fraction]] = []
    for depth in range(args.max_depth):
        order, cuts = partition_mod.derive_cuts([e["units"] for e in entries])  # type: ignore[arg-type]
        entries = [entries[i] for i in order]
        todo = [i for i, e in enumerate(entries) if e["placement"] is None]
        if not todo:
            break
        jobs = []
        keys: list[str] = []
        for i in todo:
            sub = partition_mod.sub_spec(spec, entries[i]["units"], i)  # type: ignore[arg-type]
            keys.append(_cache_key(sub, args.budget))
            for strategy in ("freeform", "sequence-pair"):
                jobs.append(
                    (sub, strategy, args.budget, loaded.belt_rules.vertical_construction, 1)
                )
        cached = [cache.get(k) for k in keys] if cache is not None else [None] * len(keys)
        hot = [n for n, got in enumerate(cached) if got is None]
        t0 = time.monotonic()
        fresh: list[tuple[dict[str, object], Placement | None]] = []
        if hot:
            work = [j for n in hot for j in jobs[2 * n : 2 * n + 2]]
            with ProcessPoolExecutor(max_workers=args.parallel) as pool:
                fresh = list(pool.map(_solve_block, work))
        solve_wall += time.monotonic() - t0
        results: list[tuple[dict[str, object], Placement | None]] = [None] * (2 * len(todo))  # type: ignore[list-item]
        for slot, n in enumerate(hot):
            results[2 * n : 2 * n + 2] = fresh[2 * slot : 2 * slot + 2]
            if cache is not None:
                cache[keys[n]] = fresh[2 * slot : 2 * slot + 2]
        for n, got in enumerate(cached):
            if got is not None:
                results[2 * n : 2 * n + 2] = got
        for k, i in enumerate(todo):
            arms = results[2 * k : 2 * k + 2]
            entries[i]["arms"] = [a[0] for a in arms]
            winners = [(a[0], a[1]) for a in arms if a[1] is not None]
            if winners:
                _, placement = min(winners, key=lambda w: placement_area(w[1]))
                entries[i]["placement"] = placement
        still = [i for i in todo if entries[i]["placement"] is None]
        rounds.append(
            {
                "depth": depth,
                "solved": len(todo) - len(still),
                "refused": len(still),
                "blocks": len(entries),
            }
        )
        if not still:
            break
        if depth == args.max_depth - 1:
            break
        # Escalate: cut every refusing block in half and try its children.
        grown: list[dict[str, object]] = []
        progress = False
        for i, entry in enumerate(entries):
            if i not in still:
                grown.append(entry)
                continue
            units: list[partition_mod.Unit] = entry["units"]  # type: ignore[assignment]
            machines = sum(u.count for u in units)
            child_cap = max(2, machines // 2)
            children = partition_mod.coalesce(partition_mod.agglomerate(units, child_cap))
            if len(children) < 2:
                grown.append(entry)
                continue
            progress = True
            grown.extend(
                {
                    "units": child,
                    "placement": None,
                    "arms": [],
                    "cap": child_cap,
                    "depth": int(entry["depth"]) + 1,  # type: ignore[call-overload]
                }
                for child in children
            )
        entries = grown
        if not progress:
            break

    if cache is not None:
        cache_path.write_bytes(pickle.dumps(cache))

    order, cuts = partition_mod.derive_cuts([e["units"] for e in entries])  # type: ignore[arg-type]
    entries = [entries[i] for i in order]
    blocks_units = [e["units"] for e in entries]
    sub_specs = [
        partition_mod.sub_spec(spec, block, i)  # type: ignore[arg-type]
        for i, block in enumerate(blocks_units)
    ]
    built = partition_mod.composed_spec(spec, blocks_units)  # type: ignore[arg-type]
    record["composed_machines"] = built.machine_count
    record["block_solve_wall_s"] = round(solve_wall, 2)
    record["escalation_rounds"] = rounds

    # A cut the prototype can wire is one item, one producing block, one
    # consuming block.  Anything else needs a splitter on a shared trunk, which
    # this spike does not emit; those items are handed back to the player as a
    # surplus output on one side and an external input on the other.
    by_item: dict[str, list[tuple[str, int, int, Fraction]]] = {}
    for cut in cuts:
        by_item.setdefault(cut[0], []).append(cut)
    surplus_by, deficit_by = partition_mod.boundary_balances(blocks_units)  # type: ignore[arg-type]
    # A cut is only wirable point-to-point when ONE producing block can feed the
    # consuming block's whole deficit.  Wiring a partial feed produces a
    # placement whose every entry lane for the item has a source and still does
    # not carry enough, and `flow.conservation`'s lane balance convicts it --
    # declaring the shortfall as an external input cannot rescue it, because
    # external supply has to arrive on an entry run and every run is now fed.
    # That is the rate half of the same lane-contract problem.
    point_to_point = [
        c
        for cs in by_item.values()
        if len(cs) == 1
        for c in cs
        if surplus_by.get(c[0], {}).get(c[1], Fraction(0))
        >= deficit_by.get(c[0], {}).get(c[2], Fraction(0))
    ]
    wirable = {(c[0], c[1], c[2]) for c in point_to_point}
    shared_trunk = [c for cs in by_item.values() for c in cs if (c[0], c[1], c[2]) not in wirable]

    record["blocks"] = [
        {
            "index": i,
            "machines": sum(u.count for u in block),  # type: ignore[attr-defined]
            "recipes": len(block),  # type: ignore[arg-type]
            "depth": entries[i]["depth"],
            "external_inputs": len(sub_specs[i].external_inputs),
            "outputs": len(sub_specs[i].outputs),
        }
        for i, block in enumerate(blocks_units)
    ]
    summary, boundaries = pressure_mod.cut_pressure(spec, blocks_units)  # type: ignore[arg-type]
    record["cut_pressure"] = summary
    record["cut_pressure_boundaries"] = boundaries
    record["cuts_point_to_point"] = [[c[0], c[1], c[2], str(c[3])] for c in point_to_point]
    record["cuts_shared_trunk"] = [[c[0], c[1], c[2], str(c[3])] for c in shared_trunk]
    record["partition_notes"] = part.notes
    # A refusing block's sub-spec is the evidence for WHY hierarchy did not
    # rescue the spec, so it is recorded rather than summarised away.
    record["refused_sub_specs"] = [
        {
            "block": i,
            "machines": sum(u.count for u in e["units"]),
            "recipes": {u.recipe: u.count for u in e["units"]},
            "machine_items": sorted({u.group.machine_item_id for u in e["units"]}),
            "external_inputs": sorted(sub_specs[i].external_inputs),
            "outputs": sorted(sub_specs[i].outputs),
            "belt_stack": sub_specs[i].belt_stack,
            "piler_unlocked": sub_specs[i].piler_unlocked,
            "spray_lanes": sorted(sub_specs[i].spray_lanes),
        }
        for i, e in enumerate(entries)
        if e["placement"] is None
    ]
    record["block_results"] = [
        {
            "block": i,
            "machines": sum(u.count for u in e["units"]),  # type: ignore[attr-defined]
            "area": None if e["placement"] is None else e["placement"].area,  # type: ignore[union-attr]
            "arms": e["arms"],
        }
        for i, e in enumerate(entries)
    ]

    best: list[Placement | None] = [e["placement"] for e in entries]  # type: ignore[misc]
    if any(p is None for p in best):
        record["verdict"] = "REFUSED: some block refused"
        record["refused_blocks"] = [i for i, p in enumerate(best) if p is None]
        record["total_wall_s"] = round(time.monotonic() - total_started, 2)
        record["uptime_end"] = _uptime()
        _write(out_label, record, None)
        print(json.dumps(record, indent=2, default=str)[:4000])
        return 1

    # --- compose ------------------------------------------------------------
    t0 = time.monotonic()
    composed = compose_mod.compose(
        [p for p in best if p is not None],
        [] if args.no_route else point_to_point,
        gap=args.gap,
        max_belt_z=loaded.belt_rules.max_z,
        single_row=args.single_row,
    )
    record["single_row"] = args.single_row
    record["compose_wall_s"] = round(time.monotonic() - t0, 2)
    record["routed"] = [[r[0], r[1], r[2], r[3]] for r in composed.routed]
    record["unrouted"] = [[u[0], u[1], u[2], u[3]] for u in composed.unrouted]
    record["corridor_tiles"] = composed.corridor_tiles

    # Anything the corridor could not wire, plus every shared trunk, is a loop
    # the player closes.  It has to be declared, or `flow.conservation` would be
    # asked to balance an item nothing delivers.
    # The handback rate is what the CUTS carry, not everything the factory makes
    # of the item: an over-declared external input would hand the lane balance a
    # supply that does not exist.  A routed lane is subtracted from the loop, so
    # an item that is half wired is handed back only for its unwired half.
    # What the player still has to belt, item by item, at the rate the CUTS
    # carry.  A corridor only counts against a consumer's deficit when EVERY
    # entry lane of that item on that block was wired -- a partially wired cut
    # is treated as unwired, because lanes do not carry equal rates and
    # pro-rating by lane count leaves `flow.conservation` short by the
    # difference (0.49 items/s on zurl2's copper-ingot).  A wired corridor is
    # then charged against its producing block's surplus, so a consumer fed by
    # a producer that has less than it needs is handed back the remainder --
    # which is what a many-to-one cut always is, and what a single
    # `flow.conservation` error on the mall's `processor` was.
    wired = {(item, src, dst) for item, src, dst, _tiles in composed.routed}
    handback: dict[str, Fraction] = {}
    open_ends: list[tuple[str, int, str]] = []
    for item, wants in deficit_by.items():
        if item in built.external_inputs:
            continue  # the player already belts this one in; it is not a cut
        spare = dict(surplus_by.get(item, {}))
        for dst, want in sorted(wants.items()):
            fed, total = composed.entry_status.get((dst, item), (0, 0))
            got = Fraction(0)
            if total and fed == total:
                for src in sorted(spare):
                    if (item, src, dst) not in wired:
                        continue
                    take = min(spare[src], want - got)
                    spare[src] -= take
                    got += take
                    if got >= want:
                        break
            if got >= want:
                continue
            handback[item] = handback.get(item, Fraction(0)) + (want - got)
            open_ends.append((item, dst, f"{fed}/{total} entry lanes wired, {got}/{want} supplied"))
    judged = _judged_spec(built, handback)
    record["player_closed_loops"] = {k: str(v) for k, v in sorted(handback.items())}
    record["player_closed_loop_count"] = len(open_ends)
    record["player_closed_loop_detail"] = [[item, dst, why] for item, dst, why in open_ends]

    # --- finalize, validate, encode ----------------------------------------
    t0 = time.monotonic()
    placement = composed.placement
    errors: list[str] = []
    try:
        placement = finalize.compact_open_boundary_belts(placement, judged, expect_power=True)
        placement = finalize.finalize_placement(placement, BandPolicy.parse("portable"))
        placement = replace(placement, completion=PlacementCompletion.COMPACTED_AND_FINALIZED)
    except finalize.ProjectionRefusal as exc:
        errors.append(f"finalize.ProjectionRefusal: {exc}"[:600])
    record["finalize_wall_s"] = round(time.monotonic() - t0, 2)

    t0 = time.monotonic()
    report = validate.validate(
        placement,
        judged,
        ids=_id_map(judged),
        expect_power=True,
        max_belt_z=loaded.belt_rules.max_z,
        belt_vertical_construction=loaded.belt_rules.vertical_construction,
    )
    record["validate_wall_s"] = round(time.monotonic() - t0, 2)
    by_class: dict[str, int] = {}
    for finding in report.findings:
        if finding.severity is validate.Severity.ERROR:
            by_class[finding.check] = by_class.get(finding.check, 0) + 1
    warn_class: dict[str, int] = {}
    for finding in report.findings:
        if finding.severity is validate.Severity.WARNING:
            warn_class[finding.check] = warn_class.get(finding.check, 0) + 1
    record["validator_errors"] = by_class
    record["validator_warnings"] = warn_class
    first_of_class: dict[str, str] = {}
    for f in report.findings:
        if f.severity is validate.Severity.ERROR:
            first_of_class.setdefault(f.check, f.message[:400])
    record["validator_error_samples"] = [f"{k}: {v}" for k, v in first_of_class.items()]
    record["validator_ok"] = report.ok and not errors
    record["finalize_errors"] = errors
    record["area"] = placement.area
    record["width"], record["height"] = (
        (placement.frame.width, placement.frame.height) if placement.frame else (None, None)
    )
    record["buildings"] = len(placement.buildings)
    record["block_area_sum"] = sum(p.area for p in best if p is not None)
    if best_known:
        record["area_ratio_vs_best_known"] = round(placement.area / best_known, 4)
    record["machines_per_tile"] = round(built.machine_count / placement.area, 5)

    blueprint = None
    if report.ok and not errors:
        marked = markers.mark_external_belts(placement, judged)
        labelled = replace(
            marked,
            short_desc=f"{args.label} hierarchical",
            description=(
                f"flab2bp hierarchical spike, {len(part.blocks)} blocks, "
                f"{built.machine_count} machines, {placement.area} tiles"
            ),
        )
        try:
            blueprint = codec.encode(labelled)
        except ValueError as exc:
            record["encode_error"] = str(exc)[:300]
    record["blueprint_emitted"] = blueprint is not None

    record["total_wall_s"] = round(time.monotonic() - total_started, 2)
    record["uptime_end"] = _uptime()
    _write(out_label, record, blueprint)
    print(json.dumps({k: v for k, v in record.items() if k != "blocks"}, indent=2)[:6000])
    return 0 if record["validator_ok"] else 2


def placement_area(placement: Placement | None) -> int:
    return placement.area if placement is not None else 1 << 30


def _judged_spec(built: BuildSpec, handback: dict[str, Fraction]) -> BuildSpec:
    """``built`` with every player-closed loop declared on both sides.

    An item the prototype could not wire leaves one block as a surplus output
    and enters another as an external input, at the rate the CUT carries -- the
    sum of the consuming blocks' deficits, never the factory's whole production
    of it.  That is a real blueprint: it asks the player for one belt per loop,
    and the count of those belts is the exact cost of not having the merge
    machinery an inter-block trunk needs.
    """
    if not handback:
        return built
    external = dict(built.external_inputs)
    surplus = dict(built.surplus_outputs)
    for item, rate in handback.items():
        if rate <= 0:
            continue
        external[item] = external.get(item, Fraction(0)) + rate
        surplus[item] = surplus.get(item, Fraction(0)) + rate
    return replace_spec(built, external_inputs=external, surplus_outputs=surplus)


def replace_spec(spec: BuildSpec, **kwargs: object) -> BuildSpec:
    data = spec.model_dump()
    data.update(kwargs)
    return BuildSpec(**data)


def _write(label: str, record: dict[str, object], blueprint: str | None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{label}.json").write_text(json.dumps(record, indent=2, default=str) + "\n")
    if blueprint:
        (OUT / f"{label}.blueprint.txt").write_text(blueprint + "\n")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONHASHSEED", "0")
    raise SystemExit(main())
