"""Record EVERY rung of the gap ladder, not just the one it commits.

`sweep_strip_cap.py` and `run_cell.py` both wrap :func:`compose.pack_with_access`
and therefore see only its RETURN value -- the rung that won.  That is enough to
say "the committed gap was 2 and its reservation was complete", which is the
whole story on four of the five composing cells.  It is NOT enough at strip cap
8, where the committed rung is gap **4** with a complete reservation: that can
only happen if rung 0 was judged and REJECTED, and the gate must not report a
rejected rung it never actually saw.

So this wraps one level lower -- `compose._pack_at` for the rung's gap and
`compose._reserve_port_access` for that rung's verdict, paired in call order --
and prints one row per rung.

    uv run python ladder_probe.py --url belt3 --policy all-products --cap 8 \
        --budget 60 --out ladder-belt3-all-products-cap8.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from sweep_strip_cap import load, unrouted_classes  # noqa: E402

from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.layout.hierarchy import compose as compose_mod  # noqa: E402
from flab2bp.layout.hierarchy.strategy import HierarchicalLayout  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="belt3")
    ap.add_argument("--policy", default="all-products")
    ap.add_argument("--cap", type=int, default=8)
    ap.add_argument("--budget", type=float, default=60.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    spec, vertical = load(args.url, args.policy)
    rungs: list[dict] = []
    original_pack_at = compose_mod._pack_at
    original_reserve = compose_mod._reserve_port_access

    def pack_at_spy(*a, **kw):
        rungs.append({"gap": kw.get("gap"), "judged": False})
        return original_pack_at(*a, **kw)

    def reserve_spy(*a, **kw):
        reservation = original_reserve(*a, **kw)
        if rungs:
            rungs[-1] |= {
                "judged": True,
                "complete": reservation.complete,
                "assigned": len(reservation.assigned),
                "missing": len(reservation.missing),
                "missing_detail": sorted(
                    f"{d.item}@belt{d.belt}:{d.kind.value}" for d in reservation.missing
                )[:40],
            }
        return reservation

    compose_mod._pack_at = pack_at_spy
    compose_mod._reserve_port_access = reserve_spy
    layout = HierarchicalLayout(
        belt_vertical_construction=vertical,
        band_policy=BandPolicy.parse("portable"),
        workers=None,
        strip_cap=args.cap,
    )
    started = time.perf_counter()
    verdict, area = "OK", None
    try:
        placement = layout.lay_out(spec, time_budget_s=args.budget)
    except NoValidLayout as exc:
        verdict = f"REFUSED: {exc.reason}"
    else:
        area = float(placement.area)
    finally:
        compose_mod._pack_at = original_pack_at
        compose_mod._reserve_port_access = original_reserve

    row = {
        "url": args.url,
        "policy": args.policy,
        "cap": args.cap,
        "budget_s": args.budget,
        "wall_s": round(time.perf_counter() - started, 1),
        "area": area,
        "verdict": verdict[:400],
        "verdict_full": verdict,
        "unrouted": unrouted_classes(verdict),
        "rungs": rungs,
    }
    print(json.dumps({k: v for k, v in row.items() if k != "verdict_full"}, indent=1))
    Path(args.out).write_text(json.dumps(row, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
