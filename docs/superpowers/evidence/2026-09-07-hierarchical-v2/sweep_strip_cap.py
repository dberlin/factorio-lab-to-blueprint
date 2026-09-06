"""Strip-cap sweep for the hierarchical strategy on the large URLs (v2 gate).

Adapted from ``../2026-09-07-hierarchical-v1/sweep_strip_cap.py``.  Three
changes, all forced by what landed on ``hierarchical-v2``:

* ``--workers`` now defaults to **None** (pass ``--workers 0`` for None
  explicitly).  v1's sweep hardcoded ``workers=16``, which was what the CLI
  effectively passed then; Task 3 changed ``pipeline.py`` so the hierarchical
  backend receives the caller's RAW ``--workers`` (``None`` when the flag is
  absent), and ``_pool_width`` then reads the box's own affinity set capped at
  ``_POOL_CAP = 32``.  A sweep at ``workers=16`` would therefore no longer be
  measuring the shipped default.
* the titanium-glass mall URL is a fourth label.
* the recorded row carries the composition GAP the ladder committed, captured
  by wrapping :func:`compose.pack_with_access` for the duration of the build.
  ``PackedCanvas.gap`` never reaches ``PlacementStats``, so this is the only
  place a gate can see which rung of ``GAP_LADDER`` won.

Two modes, as in v1:

``--probe``   partition only, milliseconds.
(default)     one real ``HierarchicalLayout.lay_out`` per cap.

The spec is built exactly the way ``tests/layout/conftest.py``'s
``mall_all_products`` fixture builds its spec.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request  # noqa: E402
from flab2bp.lab.techs import belt_rules_for_url  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.layout.hierarchy import compose as compose_mod  # noqa: E402
from flab2bp.layout.hierarchy.partition import (  # noqa: E402
    derive_cuts,
    initial_partition,
    strip_count,
)
from flab2bp.layout.hierarchy.strategy import HierarchicalLayout  # noqa: E402
from flab2bp.rates.candidates import (  # noqa: E402
    DEFAULT_CANDIDATE_POLICIES,
    _build_candidates_canonical,
)

URLS = {
    "belt3": (
        "https://factoriolab.github.io/dsp/list?o=conveyor-belt-3*1080"
        "&ibe=conveyor-belt-3&rex=P*Y*d*k*u*BN*BU*BX*Bk~Bl*Bs*CF~CG*CQ~CR"
        "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
    ),
    "zurl2": (
        "https://factoriolab.github.io/dsp/list?z=eJwVxTEKgDAMBdDbZPhTO1hcsiSom6gg2FV0EC0FRXHK2cW3vMwtvCsdZZYC4S"
        ".AO9rmlZXO9eUOEQt23JAWMkImyG5yQC5obdpAe9OBUjo5mlhlPT3s.QdXzBnL&v=11"
    ),
    "mall": (
        "https://factoriolab.github.io/dsp/list?z=eJwlx7uOwjAUhOG3OcUUKAYWhWKaY4mgVRaBEBAogRQWayVyuKTys6PEzf"
        ".NNNzAZHkmDdcnzBbD0ArTXBp-YH6kod0PtyZ-hxQSqHsgk8Bd4pLQG2Ak0Fbp223yL1Em1sfkMpEPeFoY8TyPdWPLsd3YFkZc"
        "3VMn4q41rbjuybmEuucWJ5xxxwMv9FhAN9ADtILeoI-o.9Ap7CraQrwP7GIbXSzFtx0LedOYL5cQRDE_&v=11"
    ),
    "titanium-glass": (
        "https://factoriolab.github.io/dsp/list?z=eJzLt3Uq0zI1MFDLt3VK1jI0MNDSMgSxs5DYkQi2uZaRAVzcScsYSb0RjF2C"
        "YDolaxmZwtiVIOUIvYZwThUSuwCJHQFmw3SUI.PCtAwtLS2hMoEgC0GMMCijFEWjIdzIzKRUW2e1otQK23i13Nwi28g6pzrXukC1"
        "MltDQwBw4z6V&v=11"
    ),
}


def load(label: str, policy: str):
    url = URLS[label]
    data = canonicalize_dataset(load_vendored())
    request = canonicalize_request(parse_url(url))
    rules = belt_rules_for_url(url, data)
    spec_set = _build_candidates_canonical(
        data, request, tier=None, candidate_policies=DEFAULT_CANDIDATE_POLICIES, flow=None
    )
    spec = next(c for c in spec_set.candidates if c.label == policy)
    return spec, rules.vertical_construction


def probe(spec, cap: int) -> dict:
    t0 = time.perf_counter()
    part = initial_partition(spec, strip_cap=cap)
    wall = time.perf_counter() - t0
    _order, cuts = derive_cuts(part.blocks)
    blocks = [
        {
            "machines": sum(u.count for u in b),
            "recipes": sorted({u.recipe for u in b}),
            "strips": strip_count(spec, b),
        }
        for b in part.blocks
    ]
    return {
        "cap": cap,
        "partition_wall_s": round(wall, 3),
        "blocks": len(part.blocks),
        "cuts": len(cuts),
        "strips_max": max((b["strips"] for b in blocks), default=0),
        "machines_max": max((b["machines"] for b in blocks), default=0),
        "block_detail": blocks,
    }


def build(spec, vertical: bool, cap: int, budget: float, workers: int | None) -> dict:
    layout = HierarchicalLayout(
        belt_vertical_construction=vertical,
        band_policy=BandPolicy.parse("portable"),
        workers=workers,
        strip_cap=cap,
    )
    # `PackedCanvas.gap` is the ladder's committed rung and never reaches
    # `PlacementStats`; wrap the packer for the duration of this build so the
    # gate can report the rung and the corridor verdict that chose it.
    original = compose_mod.pack_with_access
    seen: list[dict] = []

    def spy(*args, **kwargs):
        packed = original(*args, **kwargs)
        seen.append(
            {
                "gap": packed.gap,
                "missing": len(packed.reservation.missing),
                "assigned": len(packed.reservation.assigned),
                "complete": packed.reservation.complete,
            }
        )
        return packed

    compose_mod.pack_with_access = spy
    t0 = time.perf_counter()
    verdict, area, stats = "OK", None, {}
    try:
        placement = layout.lay_out(spec, time_budget_s=budget)
    except NoValidLayout as exc:
        verdict = f"REFUSED: {exc.reason}"
    else:
        area = float(placement.area)
        stats = {k: str(v) for k, v in dict(placement.stats).items()}
    finally:
        compose_mod.pack_with_access = original
    return {
        "cap": cap,
        "budget_s": budget,
        "workers": workers,
        "wall_s": round(time.perf_counter() - t0, 1),
        "verdict": verdict[:600],
        "verdict_full": verdict,
        "unrouted": unrouted_classes(verdict),
        "packings": seen,
        "area": area,
        "stats": stats,
    }


#: Router refusal reasons `compose` reports per cut lane, so a refusal can be
#: read as "the router ran out of wall" versus "the geometry refused it".
def unrouted_classes(verdict: str) -> dict[str, int]:
    marker = "unrouted cut(s): "
    if marker not in verdict:
        return {}
    counts: dict[str, int] = {}
    for item in verdict.split(marker, 1)[1].split("; "):
        reason = item.rsplit(": ", 1)[-1].strip()
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="belt3", choices=sorted(URLS))
    ap.add_argument("--policy", default="all-products")
    ap.add_argument("--caps", default="8,12,16,24")
    ap.add_argument("--budget", type=float, default=60.0)
    ap.add_argument(
        "--workers",
        type=int,
        default=0,
        help="0 (the default) means None -- what the CLI passes with no --workers",
    )
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    workers = args.workers or None
    spec, vertical = load(args.url, args.policy)
    caps = [int(c) for c in args.caps.split(",")]
    rows = []
    for cap in caps:
        row = probe(spec, cap) if args.probe else build(spec, vertical, cap, args.budget, workers)
        row |= {"url": args.url, "policy": args.policy}
        rows.append(row)
        hidden = {"block_detail", "verdict_full"}
        print(json.dumps({k: v for k, v in row.items() if k not in hidden}), flush=True)
    Path(args.out).write_text(
        json.dumps(
            {
                "url": args.url,
                "policy": args.policy,
                "machines": sum(g.count for g in spec.groups),
                "groups": len(spec.groups),
                "probe": args.probe,
                "workers": workers,
                "rows": rows,
            },
            indent=1,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
