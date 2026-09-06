"""Minimal per-spec item spread: consumer count x depth span.

Spread is computed on the recipe DAG of one ``BuildSpec``:

* ``depth(g)``   longest path from a group with no internal input to ``g``.
* ``k(item)``    number of GROUPS consuming ``item``.
* ``span(item)`` ``max(depth) - min(depth) + 1`` over those consumers.
* ``spread``     ``k * span``.

An item is INTERNAL when some group produces it (it may also be partly
external -- ``both-fed`` -- which is exactly the interesting case).

Usage:
    uv run python spread.py --url URL --policy all-products
    uv run python spread.py --corpus            # every corpus cell
"""

from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp.bench.corpus import entries_for  # noqa: E402
from flab2bp.bench.corpus import Tier  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402


def group_depths(spec) -> dict[int, int]:
    """Longest-path depth per group ordinal over the produced-by DAG."""
    producers: dict[str, list[int]] = {}
    for i, g in enumerate(spec.groups):
        for item in g.outputs_per_machine:
            producers.setdefault(item, []).append(i)
    depth: dict[int, int] = {}

    def resolve(i: int, stack: frozenset[int]) -> int:
        if i in depth:
            return depth[i]
        if i in stack:  # a recipe cycle: treat the back edge as depth 0
            return 0
        best = 0
        for item in spec.groups[i].inputs_per_machine:
            for p in producers.get(item, ()):
                if p == i:
                    continue
                best = max(best, resolve(p, stack | {i}) + 1)
        depth[i] = best
        return best

    for i in range(len(spec.groups)):
        resolve(i, frozenset())
    return depth


def spreads(spec) -> list[dict]:
    depth = group_depths(spec)
    produced = {item for g in spec.groups for item in g.outputs_per_machine}
    rows: list[dict] = []
    by_item: dict[str, list[int]] = {}
    for i, g in enumerate(spec.groups):
        for item in g.inputs_per_machine:
            by_item.setdefault(item, []).append(i)
    for item, consumers in by_item.items():
        ds = [depth[i] for i in consumers]
        span = max(ds) - min(ds) + 1
        k = len(consumers)
        demand = sum(
            (
                spec.groups[i].count * spec.groups[i].inputs_per_machine[item]
                for i in consumers
            ),
            Fraction(0),
        )
        rows.append(
            {
                "item": item,
                "internal": item in produced,
                "external_rate": float(spec.external_inputs.get(item, 0)),
                "both_fed": item in produced and item in spec.external_inputs,
                "consumers": k,
                "consumer_machines": sum(spec.groups[i].count for i in consumers),
                "depth_min": min(ds),
                "depth_max": max(ds),
                "span": span,
                "spread": k * span,
                "demand_per_s": float(demand),
                "belt_capacity": float(spec.belt_items_per_second),
                "producers": sum(
                    1 for g in spec.groups if item in g.outputs_per_machine
                ),
            }
        )
    rows.sort(key=lambda r: (-r["spread"], r["item"]))
    return rows


def spec_for(url: str, policy: CandidatePolicy):
    return build_candidates(
        load_vendored(), parse_url(url), candidate_policies=(policy,)
    ).candidates[0]


def cell_rows(label: str, url: str, policy: CandidatePolicy) -> dict:
    spec = spec_for(url, policy)
    rows = spreads(spec)
    internal = [r for r in rows if r["internal"]]
    return {
        "cell": label,
        "policy": str(policy),
        "machines": sum(g.count for g in spec.groups),
        "groups": len(spec.groups),
        "belt_stack": spec.belt_stack,
        "belt_items_per_second": float(spec.belt_items_per_second),
        "max_spread_internal": internal[0]["spread"] if internal else 0,
        "trunk_item": internal[0]["item"] if internal else None,
        "top": rows[:8],
        "top_internal": internal[:5],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--label", default="url")
    ap.add_argument("--policy", type=CandidatePolicy, default=CandidatePolicy.ALL_PRODUCTS)
    ap.add_argument("--corpus", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    out: list[dict] = []
    if args.corpus:
        for e in entries_for(*Tier):
            for pol in CandidatePolicy:
                try:
                    out.append(cell_rows(f"{e.url_id}/{pol}", e.url, pol))
                except Exception as exc:  # noqa: BLE001 - a spike report
                    out.append({"cell": f"{e.url_id}/{pol}", "error": str(exc)[:200]})
    else:
        out.append(cell_rows(args.label, args.url, args.policy))
    text = json.dumps(out, indent=1, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
