"""Throwaway probe: why does no direct insert ever land on a real corpus cell?

Instruments the three stages a direct insert has to pass and records, per strip
pair, the exact predicate that rejects it:

1. ENUMERATION -- ``_direct_net_candidate_uncached`` (recipe eligibility, lane
   match, ``_direct_origin_deltas`` geometry), broken down further into which
   of the two flow-order column filters emptied.
2. PACKING -- how many direct Booleans the CP-SAT model got and how many the
   winning pack set (``_Pack.direct``).
3. DECODE -- ``promised_direct`` versus ``realized_direct`` on the built plan.

Run: uv run python docs/.../probe_direct.py [cell ...]
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import freeform  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.rates.candidates import CandidatePolicy, build_candidates  # noqa: E402

_RANK = "arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"


def _url(target: str, *, rate: int = 60, belt: str = "conveyor-belt-2") -> str:
    return f"https://factoriolab.github.io/dsp/list?o={target}*{rate}&ibe={belt}&mmr={_RANK}&v=11"


CELLS: dict[str, tuple[str, CandidatePolicy, float]] = {
    "magnetic-coil": (_url("magnetic-coil"), CandidatePolicy.NO_PROLIFERATOR, 10.0),
    "graphene": (_url("graphene"), CandidatePolicy.NO_PROLIFERATOR, 10.0),
    "electromagnetic-matrix": (
        _url("electromagnetic-matrix"),
        CandidatePolicy.NO_PROLIFERATOR,
        10.0,
    ),
    "processor": (_url("processor"), CandidatePolicy.NO_PROLIFERATOR, 10.0),
    "casimir-crystal": (_url("casimir-crystal"), CandidatePolicy.NO_PROLIFERATOR, 10.0),
    "quantum-chip": (_url("quantum-chip"), CandidatePolicy.NO_PROLIFERATOR, 60.0),
    "super-magnetic-ring": (
        _url("super-magnetic-ring"),
        CandidatePolicy.NO_PROLIFERATOR,
        30.0,
    ),
    "information-matrix": (
        _url("information-matrix"),
        CandidatePolicy.NO_PROLIFERATOR,
        30.0,
    ),
    "qc180": (
        _url("quantum-chip", rate=180, belt="conveyor-belt-3"),
        CandidatePolicy.NO_PROLIFERATOR,
        30.0,
    ),
}


def _origin_reason(
    source, destination, source_lane, item, *, source_rate, required_rate
) -> dict[str, object]:
    """Re-derive `_direct_origin_deltas_uncached` and name the empty set."""
    out: dict[str, object] = {}
    try:
        source_plan = source._output_attachment_plan(source_lane)
        destination_plan = destination._input_attachment_plan(item)
    except (IndexError, KeyError) as exc:
        return {"reject": "attachment-plan", "detail": repr(exc)[:60]}
    if source_rate <= 0 or required_rate <= 0 or not source_plan.attachments:
        return {"reject": "rate-or-no-attachments"}
    source_machines_needed = math.ceil(required_rate / source_rate)
    if source_machines_needed > source.machines:
        return {"reject": "not-enough-source-machines"}
    last_source_injection = (source_machines_needed - 1) * source.pw + source_plan.attachments[
        0
    ].column
    first_destination_pickup = min(
        machine * destination.pw + attachment.column
        for machine in range(destination.machines)
        for attachment in destination_plan.attachments
    )
    piled = freeform._piled_output_tail_column(source, source_lane)
    if piled is not None:
        source_columns = (piled,)
    else:
        source_columns = tuple(
            c
            for c in freeform._direct_clear_columns(source, source_plan, source.width)
            if c > last_source_injection
        )
    all_source = tuple(freeform._direct_clear_columns(source, source_plan, source.width))
    destination_span = destination.input_lane_tiles(destination.lane_of_input(item))
    all_dest = tuple(
        freeform._direct_clear_columns(destination, destination_plan, destination_span)
    )
    destination_columns = tuple(c for c in all_dest if c < first_destination_pickup)
    out.update(
        item=item,
        source_machines=source.machines,
        source_machines_needed=source_machines_needed,
        source_pw=source.pw,
        source_width=source.width,
        dest_machines=destination.machines,
        dest_pw=destination.pw,
        dest_span=destination_span,
        last_source_injection=last_source_injection,
        first_destination_pickup=first_destination_pickup,
        piled_tail=piled,
        source_clear_all=all_source,
        source_clear_after_flow=source_columns,
        dest_clear_all=all_dest,
        dest_clear_after_flow=destination_columns,
    )
    if not source_columns and not destination_columns:
        out["reject"] = "both-flow-filters"
    elif not source_columns:
        out["reject"] = "source-flow-filter" if all_source else "source-no-clear-column"
    elif not destination_columns:
        out["reject"] = "dest-flow-filter" if all_dest else "dest-no-clear-column"
    else:
        out["reject"] = None
        out["deltas"] = freeform._direct_column_deltas(source_columns, sorted(destination_columns))
    return out


def probe(name: str) -> dict[str, object]:
    url, policy, budget = CELLS[name]
    data = load_vendored()
    spec = build_candidates(data, parse_url(url), candidate_policies=(policy,)).candidates[0]

    rejects: Counter[str] = Counter()
    traces: list[dict[str, object]] = []
    pack_models: list[dict[str, int]] = []
    packs_with_direct: list[int] = []

    bridges: Counter[str] = Counter()
    bridge_traces: list[dict[str, object]] = []

    orig_uncached = freeform._direct_net_candidate_uncached
    orig_pack_model = freeform._pack_model
    orig_pack_result = freeform._pack_result
    orig_bridge = freeform._bridge

    seat_rejects: list[dict[str, object]] = []
    orig_clear = freeform.slots.sorter_seat_is_clear
    in_bridge = {"on": False, "canvas": None}

    def spy_clear(candidate, buildings, standing):
        ok = orig_clear(candidate, buildings, standing)
        if ok or not in_bridge["on"] or len(seat_rejects) >= 12:
            return ok
        seat = freeform.slots.seated_sorter(candidate, buildings)
        box = freeform.colliders.sorter_box(seat)
        # Map each standing box back to the sorter that owns it, so the hit
        # names a real building rather than a floating OBB.
        owners = {}
        for other_b in buildings:
            if not freeform.catalog.is_sorter(other_b.item_id):
                continue
            other_seat = freeform.slots.seated_sorter(other_b, buildings)
            if other_seat is None:
                continue
            key = tuple(
                round(float(v), 4) for v in freeform.colliders.sorter_box(other_seat).centre
            )
            owners[key] = other_b
        hits = []
        for other in standing:
            if freeform.colliders.obb_overlap(box, other):
                key = tuple(round(float(v), 4) for v in other.centre)
                own = owners.get(key)
                hits.append(
                    {
                        "other_centre": [round(float(v), 3) for v in other.centre],
                        "other_half": [round(float(v), 3) for v in other.half],
                        "owner": None
                        if own is None
                        else {
                            "x": own.x,
                            "y": own.y,
                            "x2": own.x2,
                            "y2": own.y2,
                            "in_obj": own.input_obj,
                            "out_obj": own.output_obj,
                        },
                        "owner_seat": None
                        if own is None
                        else [
                            round(float(v), 3)
                            for v in (lambda sp: (sp.x, sp.z, sp.x2, sp.z2))(
                                freeform.slots.seated_sorter(own, buildings)
                            )
                        ],
                    }
                )
        seat_rejects.append(
            {
                "bridge_x": candidate.x,
                "bridge_y": candidate.y,
                "bridge_y2": candidate.y2,
                "box_centre": [round(float(v), 3) for v in box.centre],
                "box_half": [round(float(v), 3) for v in box.half],
                "bridge_seat": [round(float(v), 3) for v in (seat.x, seat.z, seat.x2, seat.z2)],
                "n_standing": len(standing),
                "hits": hits[:4],
                "neighbourhood": [
                    {
                        "item": freeform.catalog.building(b.item_id).name
                        if hasattr(freeform.catalog.building(b.item_id), "name")
                        else b.item_id,
                        "x": b.x,
                        "y": b.y,
                        "x2": b.x2,
                        "y2": b.y2,
                        "strip": b.owner_strip,
                        "sorter": bool(freeform.catalog.is_sorter(b.item_id)),
                        "belt": bool(freeform.catalog.is_belt(b.item_id)),
                    }
                    for b in buildings
                    if abs(b.x - candidate.x) <= 2
                    and min(candidate.y, candidate.y2) - 2
                    <= b.y
                    <= max(candidate.y, candidate.y2) + 2
                ],
            }
        )
        return ok

    def spy_bridge(
        canvas, src, dst, rates, item, standing, direct_id, *, source_rate, required_rate
    ):
        in_bridge["on"] = True
        try:
            out = orig_bridge(
                canvas,
                src,
                dst,
                rates,
                item,
                standing,
                direct_id,
                source_rate=source_rate,
                required_rate=required_rate,
            )
        finally:
            in_bridge["on"] = False
        if out is not None:
            bridges["REALIZED"] += 1
            return out
        # Re-derive the rejection.
        span = dst.y - src.y
        why = None
        detail: dict[str, object] = {
            "item": item,
            "span": span,
            "src_y": src.y,
            "dst_y": dst.y,
            "src_x": (src.x0, src.x1),
            "dst_x": (dst.x0, dst.x1),
        }
        if (
            src.cargo_domain is not freeform.CargoDomain.UNSPRAYED
            or dst.cargo_domain is not freeform.CargoDomain.UNSPRAYED
        ):
            why = "sprayed-endpoint"
        elif span < 1:
            why = "span-not-southbound"
        elif span > freeform.catalog.SORTER_MAX_REACH:
            why = "span-beyond-sorter-reach"
        else:
            b = canvas.buildings
            src_tiles = set(src.tiles)
            dst_tiles = set(dst.tiles)

            def is_machine(index):
                if not 0 <= index < len(b):
                    return False
                bl = b[index]
                return (
                    bl.owner_strip is not None
                    and not freeform.catalog.is_belt(bl.item_id)
                    and not freeform.catalog.is_sorter(bl.item_id)
                    and (bl.recipe_id not in (None, 0) or bool(bl.parameters))
                )

            inj = sorted(
                b[t].x
                for s in b
                if freeform.catalog.is_sorter(s.item_id)
                and (o := s.input_obj) is not None
                and is_machine(o)
                and (t := s.output_obj) is not None
                and t in src_tiles
            )
            pick = [
                b[s2].x
                for s in b
                if freeform.catalog.is_sorter(s.item_id)
                and (s2 := s.input_obj) is not None
                and s2 in dst_tiles
                and (t := s.output_obj) is not None
                and is_machine(t)
            ]
            needed = math.ceil(required_rate / source_rate) if source_rate > 0 else -1
            detail.update(
                injections=inj,
                pickups=sorted(pick),
                needed=needed,
                overlap=(max(src.x0, dst.x0), min(src.x1, dst.x1)),
            )
            if source_rate <= 0 or required_rate <= 0:
                why = "zero-rate"
            elif len(inj) < needed:
                why = "too-few-emitted-injections"
            else:
                last_inj = inj[needed - 1]
                first_pick = min(pick, default=None)
                detail.update(last_injection=last_inj, first_pickup=first_pick)
                cols = list(range(max(src.x0, dst.x0), min(src.x1, dst.x1) + 1))
                after = [c for c in cols if c > last_inj]
                before = [c for c in after if first_pick is None or c < first_pick]
                blocked = [
                    c
                    for c in before
                    if (c, src.y, 0) in canvas.blocked and (c, dst.y, 0) in canvas.blocked
                ]
                detail.update(
                    n_overlap_cols=len(cols),
                    n_after_injection=len(after),
                    n_before_pickup=len(before),
                    n_both_lanes_present=len(blocked),
                )
                if not cols:
                    why = "no-column-overlap"
                elif not after:
                    why = "flow-order-source-side"
                elif not before:
                    why = "flow-order-destination-side"
                elif not blocked:
                    why = "no-shared-blocked-column"
                else:
                    why = "sorter-seat-collision"
        bridges[str(why)] += 1
        if len(bridge_traces) < 12:
            detail["why"] = why
            bridge_traces.append(detail)
        return out

    def _dest_lane_picture(destination, item) -> dict[str, object]:
        """Every input lane's row and machine-0 attachment column."""
        bridged_row = destination._input_attachment_plan(item).lane_y
        lanes = []
        for lane in destination.in_above + destination.in_below:
            plan = destination._input_attachment_plan(lane[0])
            lanes.append(
                {
                    "items": list(lane),
                    "lane_y": plan.lane_y,
                    "columns": sorted({a.column for a in plan.attachments}),
                    "bridged": lane == destination.lane_of_input(item),
                }
            )
        # A sorter from lane L to the machine band crosses the bridged lane's row
        # when the bridged row lies strictly between L's row and the band.
        band = destination.machine_row
        crossing = sorted(
            {
                c
                for lane in lanes
                if not lane["bridged"]
                and ((lane["lane_y"] < bridged_row < 0) or (0 <= bridged_row < lane["lane_y"]))
                for c in lane["columns"]
            }
        )
        return {
            "machine_row": band,
            "bridged_lane_y": bridged_row,
            "lanes": lanes,
            "crossing_columns": crossing,
        }

    def spy_uncached(source, destination, groups, eligible):
        out = orig_uncached(source, destination, groups, eligible)
        if out is not None:
            rejects["ACCEPTED"] += 1
            if len(traces) < 40:
                item = out.item
                first_pickup = min(
                    m * destination.pw + a.column
                    for m in range(destination.machines)
                    for a in destination._input_attachment_plan(item).attachments
                )
                span = destination.input_lane_tiles(destination.lane_of_input(item))
                legal = sorted(
                    c
                    for c in freeform._direct_clear_columns(
                        destination,
                        destination._input_attachment_plan(item),
                        span,
                    )
                    if c < first_pickup
                )
                pic = _dest_lane_picture(destination, item)
                traces.append(
                    {
                        "stage": "accepted",
                        "item": item,
                        "source_recipe": source.recipe_id,
                        "dest_recipe": destination.recipe_id,
                        "dest_machines": destination.machines,
                        "dest_pw": destination.pw,
                        "first_pickup": first_pickup,
                        "flow_legal_columns": legal,
                        "crossing_columns": pic["crossing_columns"],
                        "legal_minus_crossing": sorted(set(legal) - set(pic["crossing_columns"])),
                        "lanes": pic["lanes"],
                    }
                )
            return out
        if source.takes_belt_ports:
            rejects["source-takes-belt-ports"] += 1
            return out
        if (source.recipe_id, destination.recipe_id) not in eligible:
            rejects["recipe-pair-not-eligible"] += 1
            return out
        lane = next(
            (
                (k, item)
                for k, (item, dest, cargo) in enumerate(source.out_lanes)
                if cargo is freeform.CargoDomain.UNSPRAYED
                and destination.group_key in freeform._dests(dest)
            ),
            None,
        )
        if lane is None:
            rejects["no-unsprayed-lane-to-dest"] += 1
            return out
        k, item = lane
        if item not in destination.in_lanes:
            rejects["item-not-in-dest-lanes"] += 1
            return out
        source_rate = groups[source.group_key].outputs.get(item, Fraction(0))
        required_rate = destination.machines * groups[destination.group_key].inputs.get(
            item, Fraction(0)
        )
        reason = _origin_reason(
            source,
            destination,
            k,
            item,
            source_rate=source_rate,
            required_rate=required_rate,
        )
        rejects[str(reason["reject"])] += 1
        if len(traces) < 24:
            reason["source_recipe"] = source.recipe_id
            reason["dest_recipe"] = destination.recipe_id
            traces.append(reason)
        return out

    def spy_pack_model(strips, **kwargs):
        built = orig_pack_model(strips, **kwargs)
        pack_models.append(
            {
                "n_direct_vars": 0 if built is None else len(built.direct_vars),
                "n_candidates": len(kwargs.get("direct_candidates") or {}),
            }
        )
        return built

    def spy_pack_result(built, solver, strips, direct_candidates, *args, **kwargs):
        outcome = orig_pack_result(built, solver, strips, direct_candidates, *args, **kwargs)
        if outcome.pack is not None:
            packs_with_direct.append(len(outcome.pack.direct))
            if len(built.direct_vars) and len(traces) < 40:
                traces.append(
                    {
                        "stage": "pack",
                        "status": outcome.status,
                        "objective": outcome.objective_value,
                        "n_direct_vars": len(built.direct_vars),
                        "direct_set": len(outcome.pack.direct),
                        "width": outcome.pack.width,
                        "height": outcome.pack.height,
                    }
                )
        return outcome

    freeform._direct_net_candidate_uncached = spy_uncached
    freeform._pack_model = spy_pack_model
    freeform._pack_result = spy_pack_result
    freeform._bridge = spy_bridge
    freeform.slots.sorter_seat_is_clear = spy_clear
    try:
        # workers=1 keeps every stage in this process so the spies actually see it.
        layout = freeform.FreeformLayout(band_policy=BandPolicy("portable"), workers=1)
        try:
            placement = layout.lay_out(spec, time_budget_s=budget)
            stats = {
                k: float(v)
                for k, v in placement.stats.items()
                if isinstance(v, (int, float))
                and k
                in {
                    "direct_inserts",
                    "direct_insert_candidates",
                    "strips",
                    "machines",
                    "nets",
                    "belt_tiles",
                }
            }
            stats["area"] = float(placement.area)
            verdict = "CLEAN"
        except Exception as exc:  # noqa: BLE001 - a refusal is a datum here
            stats = {}
            verdict = repr(exc)[:100]
    finally:
        freeform._direct_net_candidate_uncached = orig_uncached
        freeform._pack_model = orig_pack_model
        freeform._pack_result = orig_pack_result
        freeform._bridge = orig_bridge
        freeform.slots.sorter_seat_is_clear = orig_clear

    return {
        "cell": name,
        "verdict": verdict,
        "stats": stats,
        "recipe_pair_candidates": len(freeform._direct_insert_candidates(spec)),
        "enumeration_rejects": dict(rejects.most_common()),
        "pack_models": {
            "solves": len(pack_models),
            "with_direct_vars": sum(1 for m in pack_models if m["n_direct_vars"]),
            "max_direct_vars": max((m["n_direct_vars"] for m in pack_models), default=0),
            "max_candidates_in": max((m["n_candidates"] for m in pack_models), default=0),
        },
        "packs": {
            "decoded": len(packs_with_direct),
            "with_direct_set": sum(1 for n in packs_with_direct if n),
            "max_direct_set": max(packs_with_direct, default=0),
        },
        "bridges": dict(bridges.most_common()),
        "seat_rejects": seat_rejects,
        "traces": traces,
        "bridge_traces": bridge_traces,
    }


def main(argv: list[str]) -> int:
    names = argv[1:] or ["magnetic-coil"]
    out = []
    for name in names:
        row = probe(name)
        out.append(row)
        summary = dict(row)
        summary.pop("traces")
        summary.pop("bridge_traces")
        summary["seat_rejects"] = summary["seat_rejects"][:3]
        print(json.dumps(summary, indent=1, default=str), flush=True)
    dest = Path(__file__).with_name("probe-direct.json")
    dest.write_text(json.dumps(out, indent=1, default=str))
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
