"""Render the README tables from ``out/*.json``.

uv run python docs/superpowers/evidence/2026-09-06-exp-hierarchical/proto/table.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "out"
ORDER = (
    "belt3",
    "belt3-blocks-only",
    "belt3-depth-pressure",
    "belt3-depth-pressure-blocks-only",
    "zurl2",
    "zurl2-blocks-only",
    "mall",
    "mall-blocks-only",
    "mall-no-proliferator",
    "mall-no-proliferator-blocks-only",
)


def main() -> None:
    rows = []
    for label in ORDER:
        path = OUT / f"{label}.json"
        if not path.exists():
            continue
        rows.append((label, json.loads(path.read_text())))

    print(
        "| case | machines | blocks | block sizes | serial block wall | "
        "critical-path block wall | compose+finalize+validate | measured total |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for label, d in rows:
        sizes = sorted((b["machines"] for b in d["blocks"]), reverse=True)
        walls = [[float(a["wall_s"]) for a in r["arms"]] for r in d["block_results"] if r["arms"]]
        serial = sum(sum(w) for w in walls)
        critical = max((max(w) for w in walls), default=0.0)
        post = round(
            sum(
                float(d.get(k) or 0)
                for k in ("compose_wall_s", "finalize_wall_s", "validate_wall_s")
            ),
            2,
        )
        print(
            f"| `{label}` | {d['machines']} | {len(d['blocks'])} | "
            f"{min(sizes)}-{max(sizes)} (median {sorted(sizes)[len(sizes) // 2]}) | "
            f"{serial:.1f} s | {critical:.1f} s | {post} s | "
            f"{d.get('total_wall_s')} s |"
        )

    print()
    print(
        "| case | verdict | validator errors | area | sum of blocks | best known | "
        "ratio | machines/tile |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for label, d in rows:
        if d.get("verdict"):
            print(f"| `{label}` | {d['verdict']} | - | - | - | - | - | - |")
            continue
        errs = d.get("validator_errors") or {}
        best = d.get("best_known_area")
        ratio = d.get("area_ratio_vs_best_known")
        print(
            f"| `{label}` | {'CLEAN' if d.get('blueprint_emitted') else 'INVALID'} | "
            f"{sum(errs.values()) or 0}{' ' + str(errs) if errs else ''} | {d.get('area')} | "
            f"{d.get('block_area_sum')} | {best or 'none'} | "
            f"{ratio if ratio else '-'} | {d.get('machines_per_tile')} |"
        )

    print()
    print(
        "| case | item pressure | lane pressure | worst boundary lanes | cuts p2p | "
        "cuts shared | routed | unrouted | corridor tiles | player loops |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for label, d in rows:
        if d.get("verdict"):
            continue
        cp = d.get("cut_pressure") or {}
        print(
            f"| `{label}` | {cp.get('item_pressure')} | {cp.get('lane_pressure')} | "
            f"{cp.get('max_boundary_lane_pressure')} | "
            f"{len(d['cuts_point_to_point'])} | {len(d['cuts_shared_trunk'])} | "
            f"{len(d.get('routed') or [])} | {len(d.get('unrouted') or [])} | "
            f"{d.get('corridor_tiles')} | {len(d.get('player_closed_loops') or [])} |"
        )

    print()
    print("### belt3 depth pressure profile (both arms see the same profile)")
    print()
    for label, d in rows:
        profile = d.get("depth_pressure_profile")
        if not profile or not label.startswith("belt3"):
            continue
        print(
            "| cut after depth | recipes below | machines below | "
            "item pressure | lane pressure |"
        )
        print("| --- | --- | --- | --- | --- |")
        for r in profile:
            print(
                f"| {r['cut_after_depth']} | {r['recipes_below']} | {r['machines_below']} | "
                f"{r['item_pressure']} | {r['lane_pressure']} |"
            )
        break

    print()
    for label, d in rows:
        print(f"### `{label}` unrouted cuts")
        for item, src, dst, why in d.get("unrouted") or []:
            print(f"* `{item}` block {src} -> {dst}: {why}")
        print()
        warns = d.get("validator_warnings") or {}
        print(f"warnings: {warns}")
        print(f"uptime at start: `{d.get('uptime_start')}`")
        print(f"uptime at end:   `{d.get('uptime_end')}`")
        print()


if __name__ == "__main__":
    main()
