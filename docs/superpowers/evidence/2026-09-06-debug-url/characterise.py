"""Describe the user's URL as a spec, before any layout runs.

Everything here is cheap: candidate construction plus strip planning plus the
pre-placement routing features.  No placer is invoked, so this is safe to run
while a gate holds the box.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "docs/superpowers/evidence/2026-09-06-exp-features"))

import routing_features as rf  # noqa: E402

from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402


def _f(value: Fraction) -> float:
    return round(float(value), 4)


def describe(spec) -> dict[str, object]:  # noqa: ANN001
    row: dict[str, object] = {
        "label": spec.label,
        "machines": sum(g.count for g in spec.groups),
        "groups": len(spec.groups),
        "belt": spec.belt_item_id,
        "belt_ips": _f(spec.belt_items_per_second),
        "belt_upgrades": [t.item_id for t in spec.belt_upgrades],
        "belt_stack": spec.belt_stack,
        "piler_unlocked": spec.piler_unlocked,
        "external_inputs": {k: _f(v) for k, v in sorted(spec.external_inputs.items())},
        "outputs": {k: _f(v) for k, v in sorted(spec.outputs.items())},
        "surplus_outputs": {k: _f(v) for k, v in sorted(spec.surplus_outputs.items())},
        "spray_lanes": dict(sorted(spec.spray_lanes.items())),
        "lanes_requiring_split": sorted(spec.lanes_requiring_split),
        "belt_required_edges": sorted(map(list, spec.belt_required_edges)),
        "recipes": [
            {
                "recipe": g.recipe_id,
                "machine": g.machine_item_id,
                "count": g.count,
                "prolif": str(g.proliferator_mode),
            }
            for g in spec.groups
        ],
    }
    try:
        row["lane_capacity"] = _f(rf.lane_capacity(spec))
        row["items_above_one_belt"] = list(rf.items_above_one_belt(spec))
    except Exception as exc:  # noqa: BLE001
        row["lane_capacity_error"] = f"{type(exc).__name__}: {exc}"
    try:
        strips = rf.plan_strips_for(spec)
        n, widest, mean = rf.strip_shape(strips)
        row["strips"] = {"n": n, "widest": widest, "mean": round(mean, 3)}
        row["strip_machines"] = [s.machines for s in strips]
        row["strip_recipes"] = sorted({s.recipe_id for s in strips})
    except Exception as exc:  # noqa: BLE001
        row["strips_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from flab2bp.layout.strip_variants import _logical_strip_plans

        plans = _logical_strip_plans(spec)
        row["logical_strip_plans"] = len(plans)
    except Exception as exc:  # noqa: BLE001
        row["strips_error"] = f"{type(exc).__name__}: {exc}"
    try:
        feats = rf.routing_features(spec)
        row["features"] = {
            f.name: (
                round(getattr(feats, f.name), 4)
                if isinstance(getattr(feats, f.name), float)
                else getattr(feats, f.name)
            )
            for f in dataclasses.fields(feats)
        }
    except Exception as exc:  # noqa: BLE001
        row["features_error"] = f"{type(exc).__name__}: {exc}"
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    parsed = parse_url(args.url)
    out: dict[str, object] = {
        "url": args.url,
        "parsed": {
            k: str(getattr(parsed, k))
            for k in sorted(dir(parsed))
            if not k.startswith("_") and not callable(getattr(parsed, k, None))
        },
        "candidates": [],
    }
    for policy in CandidatePolicy:
        try:
            built = build_candidates(load_vendored(), parsed, candidate_policies=(policy,))
        except Exception as exc:  # noqa: BLE001
            out["candidates"].append(  # type: ignore[union-attr]
                {"policy": str(policy), "error": f"{type(exc).__name__}: {exc}"}
            )
            continue
        for spec in built.candidates:
            row = describe(spec)
            row["policy"] = str(policy)
            out["candidates"].append(row)  # type: ignore[union-attr]

    text = json.dumps(out, indent=2, sort_keys=False, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
