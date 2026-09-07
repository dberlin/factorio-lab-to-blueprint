"""Build ONE audit cell in the current ``FLAB2BP_COATER_NODE`` arm and report.

    FLAB2BP_COATER_NODE=seat uv run python probe_cell.py <url_id> <policy> \
        [--strategy freeform|sequence-pair] [--budget 30] [--bp out.txt]

Prints every validator finding, the coater count, and for each coater the lane
tiles its body covers together with the belt predecessors of each of those
tiles -- which is the reported defect, stated directly rather than inferred.
"""

from __future__ import annotations

import argparse
import os
import time
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.dsp import catalog
from flab2bp.dsp.records import is_belt
from flab2bp.lab.data import load_vendored
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.lab.url import parse_url
from flab2bp.layout import validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import PlacementCompletion
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url_id")
    ap.add_argument("policy")
    ap.add_argument("--strategy", default="freeform")
    ap.add_argument("--budget", type=float, default=30.0)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--bp", default="")
    ap.add_argument("--url", default="")
    args = ap.parse_args()

    url = args.url
    if not url:
        url = next(e.url for e in URL_CORPUS if e.url_id == args.url_id)
    data = load_vendored()
    specs = build_candidates(
        data,
        parse_url(url),
        candidate_policies=DEFAULT_CANDIDATE_POLICIES,
    ).candidates
    spec = next(s for s in specs if s.label == args.policy)
    rules = belt_rules_for_url(url, data)

    if args.strategy == "freeform":
        strategy = FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=args.workers,
            belt_vertical_construction=rules.vertical_construction,
        )
    else:
        strategy = SequencePairLayout(
            band_policy=BandPolicy("portable"),
            belt_vertical_construction=rules.vertical_construction,
            islands=1,
        )

    print(f"arm={os.environ.get('FLAB2BP_COATER_NODE', 'off')} "
          f"cell={args.url_id}/{args.policy} strategy={args.strategy}")
    t0 = time.monotonic()
    try:
        placement = strategy.lay_out(spec, time_budget_s=args.budget)
    except Exception as exc:  # noqa: BLE001
        print(f"REFUSED/CRASH {type(exc).__name__}: {exc}")
        return
    wall = time.monotonic() - t0
    from dataclasses import replace

    from flab2bp.layout import finalize

    if placement.completion is not PlacementCompletion.COMPACTED_AND_FINALIZED:
        placement = finalize.compact_open_boundary_belts(placement, spec, expect_power=True)
        try:
            placement = finalize.finalize_placement(placement, BandPolicy("portable"))
        except finalize.ProjectionRefusal as exc:
            print(f"REFUSED projection: {exc.checks}")
            return
        placement = replace(placement, completion=PlacementCompletion.COMPACTED_AND_FINALIZED)
    report = validate.validate(
        placement,
        spec,
        max_belt_z=rules.max_z,
        belt_vertical_construction=rules.vertical_construction,
    )
    bs = placement.buildings
    coaters = [(i, b) for i, b in enumerate(bs) if b.item_id == catalog.SPRAY_COATER_ID]
    belts = [(i, b) for i, b in enumerate(bs) if is_belt(b.item_id)]
    at: dict[tuple[int, int, Fraction], int] = {(b.x, b.y, b.z): i for i, b in belts}
    pred: dict[int, list[int]] = defaultdict(list)
    for i, b in belts:
        if b.output_obj is not None and 0 <= b.output_obj < len(bs):
            pred[b.output_obj].append(i)

    merges = 0
    for i, c in coaters:
        span = catalog.oriented_footprint(catalog.SPRAY_COATER_ID, c.yaw)
        half = (span[0] - 1) // 2
        covered = [(c.x + dx, c.y, c.z) for dx in range(-half, half + 1)]
        for cell in covered:
            belt = at.get(cell)
            if belt is None:
                continue
            if len(pred[belt]) > 1:
                merges += 1
                print(f"  MERGE-UNDER-BODY coater#{i}@({c.x},{c.y},{c.z}) "
                      f"belt#{belt}@{cell} pred={pred[belt]}")

    print(f"wall={wall:.1f}s buildings={len(bs)} coaters={len(coaters)} "
          f"belts={len(belts)} coater_merges={merges}")
    print(f"area={placement.stats.get('area')} "
          f"belt_tiles={sum(1 for _ in belts)}")
    for f in report.findings:
        print(f"  {f.severity.name} {f.check}: {f.message[:180]}")
    if not report.findings:
        print("  (no findings)")
    import hashlib

    digest = hashlib.sha256(
        "\n".join(
            f"{b.item_id},{b.model_index},{b.x},{b.y},{b.z},{b.yaw},"
            f"{b.input_obj},{b.output_obj},{b.recipe_id},{b.filter_id},{b.carries_item}"
            for b in bs
        ).encode()
    ).hexdigest()[:16]
    print(f"digest={digest}")
    if args.bp:
        from flab2bp.dsp import codec

        Path(args.bp).write_text(codec.encode(placement))


if __name__ == "__main__":
    main()
