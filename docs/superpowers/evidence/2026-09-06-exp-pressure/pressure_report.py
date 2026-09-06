"""What arm A would buy on each cell, with no layout run.

Prints the cut profile, the rows the switch charges, and the reserved area
that costs -- the numbers the tuning of ``LANES_PER_EXTRA_ROW`` is frozen
against, and the denominator for "did the extra corridor get used".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "src"))

os.environ["FLAB2BP_PRESSURE_CORRIDORS"] = "1"

from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import pressure  # noqa: E402
from flab2bp.layout.freeform import _box, plan_strips  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402

sys.path.insert(0, str(HERE.parent / "2026-09-05-scale-profile"))
from prof_harness import make_url  # noqa: E402

LARGE_URLS = ROOT / "docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt"


def urls() -> dict[str, str]:
    return {
        line.split("\t", 1)[0].strip(): line.split("\t", 1)[1].strip()
        for line in LARGE_URLS.read_text().splitlines()
        if line.strip()
    }


def report(label: str, url: str, policy: str) -> dict[str, object]:
    spec = build_candidates(
        load_vendored(), parse_url(url), candidate_policies=(CandidatePolicy(policy),)
    ).candidates[0]
    strips = plan_strips(spec)
    lanes = pressure.lane_pressure_by_cut(spec)
    depths = pressure.strip_depths(spec, strips)
    rows = tuple(strip.south_channel for strip in strips)
    boxes = [_box(strip) for strip in strips]
    #: What the pack would be without the switch, and the ground the extra rows
    #: add: the honest denominator for "was the corridor worth its area".
    base_area = sum(w * (h - extra) for (w, h), extra in zip(boxes, rows, strict=True))
    extra_area = sum(w * extra for (w, _h), extra in zip(boxes, rows, strict=True))
    return {
        "label": label,
        "policy": policy,
        "strips": len(strips),
        "chain_depth": len(lanes),
        "lane_pressure_by_cut": list(lanes),
        "max_lane_pressure": max(lanes) if lanes else 0,
        "strips_widened": sum(1 for r in rows if r),
        "rows_bought": sum(rows),
        "rows_by_depth": {
            str(d): sorted({r for dd, r in zip(depths, rows, strict=True) if dd == d})
            for d in sorted(set(depths))
        },
        "box_area_without_switch": base_area,
        "box_area_added": extra_area,
        "box_area_added_pct": round(100.0 * extra_area / base_area, 2) if base_area else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "arm-a-cost.json"))
    args = ap.parse_args()
    large = urls()
    grid = [
        ("um60", make_url("universe-matrix", 60), "no-proliferator"),
        ("um120", make_url("universe-matrix", 120), "no-proliferator"),
        ("gm200", make_url("gravity-matrix", 200), "no-proliferator"),
        ("qc180", make_url("quantum-chip", 180), "no-proliferator"),
        ("belt3-all", large["belt3"], "all-products"),
        ("belt3-nopro", large["belt3"], "no-proliferator"),
        ("mall", large["mall"], "all-products"),
        ("zurl2", large["zurl2"], "all-products"),
    ]
    from flab2bp.bench.corpus import URL_CORPUS

    by_id = {entry.url_id: entry.url for entry in URL_CORPUS}
    for url_id, policy in (
        ("universe-matrix", "all-products"),
        ("universe-matrix", "output-products"),
        ("universe-matrix", "no-proliferator"),
        ("quantum-chip", "all-products"),
        ("quantum-chip", "output-products"),
        ("quantum-chip", "no-proliferator"),
        ("information-matrix", "all-products"),
        ("information-matrix", "output-products"),
    ):
        grid.append((f"{url_id}/{policy}", by_id[url_id], policy))

    out = []
    for label, url, policy in grid:
        row = report(label, url, policy)
        out.append(row)
        print(
            f'{label:34s} d={row["chain_depth"]:2d} maxlp={row["max_lane_pressure"]:3d} '
            f'widened={row["strips_widened"]:3d}/{row["strips"]:3d} '
            f'rows={row["rows_bought"]:3d} +area={row["box_area_added_pct"]:5.2f}% '
            f'profile={row["lane_pressure_by_cut"]}',
            flush=True,
        )
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
