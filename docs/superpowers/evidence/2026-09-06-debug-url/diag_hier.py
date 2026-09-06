"""Catch the composed spec and placement the hierarchical strategy validates.

``HierarchicalLayout.lay_out`` calls ``validate.certify(placement, built, ...)``
and turns a non-ok report into a refusal string.  The string names the item and
the shortfall but not the rate arithmetic behind it, so this wraps ``certify``
to capture both arguments and then reports, per item, what the composed spec
says is produced against what it says is consumed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import validate  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.layout.hierarchy import strategy as hstrategy  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402


def balance(spec) -> dict[str, dict[str, str]]:  # noqa: ANN001
    made: dict[str, Fraction] = defaultdict(Fraction)
    used: dict[str, Fraction] = defaultdict(Fraction)
    for group in spec.groups:
        for item, rate in group.outputs_per_machine.items():
            made[item] += rate * group.count
        for item, rate in group.inputs_per_machine.items():
            used[item] += rate * group.count
    rows = {}
    for item in sorted(set(made) | set(used)):
        m, u = made[item], used[item]
        ext = spec.external_inputs.get(item, Fraction(0))
        out = spec.outputs.get(item, Fraction(0)) + spec.surplus_outputs.get(item, Fraction(0))
        rows[item] = {
            "made": str(m),
            "used": str(u),
            "external_in": str(ext),
            "belted_out": str(out),
            "slack": str(m + ext - u - out),
        }
    return rows


def counts(spec) -> dict[str, int]:  # noqa: ANN001
    out: dict[str, int] = defaultdict(int)
    for group in spec.groups:
        out[group.recipe_id] += group.count
    return dict(sorted(out.items()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--policy", default="output-products")
    ap.add_argument("--budget", type=float, default=60.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dump", type=Path, help="pickle (placement, composed spec) on failure")
    args = ap.parse_args()

    asked = build_candidates(
        load_vendored(),
        parse_url(args.url),
        candidate_policies=(CandidatePolicy(args.policy),),
    ).candidates[0]

    captured: dict[str, object] = {}
    real_certify = validate.certify

    def spy(placement, spec, **kwargs):  # noqa: ANN001, ANN003
        report = real_certify(placement, spec, **kwargs)
        captured["built_counts"] = counts(spec)
        captured["built_balance"] = balance(spec)
        captured["built_external_inputs"] = {
            k: str(v) for k, v in sorted(spec.external_inputs.items())
        }
        captured["report_ok"] = report.ok
        if not report.ok and args.dump:
            import pickle

            args.dump.write_bytes(pickle.dumps((placement, spec)))
        captured["errors"] = [
            {"check": f.check, "detail": f.detail, "buildings": list(f.buildings)[:6]}
            for f in report.errors
        ]
        return report

    hstrategy.validate.certify = spy  # type: ignore[attr-defined]

    from flab2bp.layout.hierarchy import contracts as C

    apportion_log: list[dict[str, object]] = []
    real_apportion = C._apportion

    def apportion_spy(total, buildings, indices, **kw):  # noqa: ANN001, ANN003
        strips = [buildings[i].owner_strip for i in indices]
        puts_on = kw.get("puts_on", True)
        weights = [
            C._machines_on_lane(buildings, i, puts_on=puts_on)
            if s is None
            else C._machines_behind(buildings, s)
            for i, s in zip(indices, strips, strict=True)
        ]
        parts = real_apportion(total, buildings, indices, **kw)
        apportion_log.append(
            {
                "total": str(total),
                "lanes": indices,
                "item": [buildings[i].carries_item for i in indices],
                "owner_strips": strips,
                "machines_behind": weights,
                "even_split_fallback": sum(w or 0 for w in weights) == 0,
                "parts": [str(p) for p in parts],
            }
        )
        return parts

    C._apportion = apportion_spy  # type: ignore[assignment]
    captured["apportion"] = apportion_log

    real_assign = hstrategy.assign_lanes

    def assign_spy(cuts, tails, heads):  # noqa: ANN001
        flows = real_assign(cuts, tails, heads)
        captured["flows"] = [
            {
                "item": f.item,
                "rate": str(f.rate),
                "src": [f.src.block, f.src.building, str(f.src.rate)],
                "dst": [f.dst.block, f.dst.building, str(f.dst.rate)],
            }
            for f in flows
        ]
        return flows

    hstrategy.assign_lanes = assign_spy  # type: ignore[assignment]

    real_compose = hstrategy.compose_mod.compose

    def compose_spy(*a, **k):  # noqa: ANN002, ANN003
        result = real_compose(*a, **k)
        captured["compose_routed"] = result.routed
        captured["compose_failures"] = list(result.failures)
        captured["compose_blocks"] = [
            {
                "index": b.index,
                "base": b.base,
                "offset": list(b.offset),
                "w": b.width,
                "h": b.height,
            }
            for b in result.blocks
        ]
        return result

    hstrategy.compose_mod.compose = compose_spy  # type: ignore[assignment]

    layout = hstrategy.HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy("portable"),
        workers=args.workers,
    )
    row: dict[str, object] = {
        "policy": args.policy,
        "budget_s": args.budget,
        "asked_counts": counts(asked),
        "asked_balance": balance(asked),
    }
    t0 = time.perf_counter()
    try:
        placement = layout.lay_out(asked, time_budget_s=args.budget)
    except NoValidLayout as exc:
        row["verdict"] = "REFUSED"
        row["reason"] = exc.reason
        row["stats"] = {k: str(v) for k, v in sorted(exc.stats.items())}
    else:
        row["verdict"] = "OK"
        row["area"] = int(placement.area)
    row["wall_s"] = round(time.perf_counter() - t0, 2)
    row.update(captured)

    text = json.dumps(row, indent=2, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
