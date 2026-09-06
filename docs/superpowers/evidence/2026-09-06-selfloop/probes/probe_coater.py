"""Throwaway probe: what belt geometry sits under and around each Spray Coater.

Usage:
    uv run python .../probe_coater.py <blueprint.txt>

For every coater: its footprint tiles, every belt within 2 tiles (with run id,
z, and the run's predecessor/successor links), the belt runs that MERGE into the
tiles the coater covers, and the resolved addon areas (cargo belt + proliferator
supply) with the nearest belt to each.
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from pathlib import Path

from flab2bp.dsp import catalog, rules
from flab2bp.dsp.codec import decode
from flab2bp.dsp.records import is_belt, is_sorter

_ITEM_NAMES = {v: k for k, v in catalog._item_ids().items()}  # noqa: SLF001 - probe


def name_of(item_id: int) -> str:
    return _ITEM_NAMES.get(item_id, f"item#{item_id}")


def main() -> None:
    bp = decode(Path(sys.argv[1]).read_text().strip())
    b = bp.buildings
    by_index = {x.index: x for x in b}
    belts = [x for x in b if is_belt(x.item_id)]
    belt_ids = {x.index for x in belts}

    succ: dict[int, int] = {}
    pred: dict[int, list[int]] = defaultdict(list)
    for x in belts:
        if x.output_obj_idx in belt_ids:
            succ[x.index] = x.output_obj_idx
            pred[x.output_obj_idx].append(x.index)

    runs: list[list[int]] = []
    seen: set[int] = set()
    for h in [x.index for x in belts if not pred[x.index]]:
        chain: list[int] = []
        cur: int | None = h
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            cur = succ.get(cur)
        runs.append(chain)
    for x in belts:
        if x.index not in seen:
            chain = []
            cur = x.index
            while cur is not None and cur not in seen:
                seen.add(cur)
                chain.append(cur)
                cur = succ.get(cur)
            if chain:
                runs.append(chain)
    run_of = {idx: i for i, chain in enumerate(runs) for idx in chain}

    run_items: dict[int, set[str]] = defaultdict(set)
    for s in b:
        if not is_sorter(s.item_id) or not s.filter_id:
            continue
        for peer in (s.input_obj_idx, s.output_obj_idx):
            if peer in run_of:
                run_items[run_of[peer]].add(name_of(s.filter_id))

    coater = catalog.building(catalog.SPRAY_COATER_ID)
    print("Spray Coater footprint:", catalog.footprint(catalog.SPRAY_COATER_ID))
    print("addon_areas:", coater.addon_areas)
    print("ADDON_AREA_RADIUS:", rules.ADDON_AREA_RADIUS)
    print()

    for m in b:
        if m.item_id != catalog.SPRAY_COATER_ID:
            continue
        print(f"=== coater#{m.index} at ({m.x},{m.y},{m.z}) yaw={m.yaw} ===")
        w, h = catalog.footprint(catalog.SPRAY_COATER_ID)
        # tiles the coater body covers, for both yaw readings
        near = [
            e
            for e in belts
            if abs(e.x - m.x) <= 2.5 and abs(e.y - m.y) <= 2.5
        ]
        print("  belts within 2.5 tiles:")
        for e in sorted(near, key=lambda t: (t.z, t.y, t.x)):
            r = run_of[e.index]
            p = [q for q in pred[e.index]]
            s = succ.get(e.index)
            print(
                f"    belt#{e.index} ({e.x},{e.y},{e.z}) run {r} items={sorted(run_items[r]) or '[]'}"
                f" pred={p} succ={s}"
                f"{'   <<< MERGE POINT (%d predecessors)' % len(p) if len(p) > 1 else ''}"
            )
        # resolve addon areas both ways
        for area in coater.addon_areas:
            for sign, label in ((1, "yaw+"), (-1, "yaw-")):
                theta = math.radians(m.yaw * sign)
                lx, ly, lz = float(area.dx), float(area.dy), float(area.dz)
                wx = m.x + lx * math.cos(theta) - ly * math.sin(theta)
                wy = m.y + lx * math.sin(theta) + ly * math.cos(theta)
                wz = m.z + lz
                best = None
                for e in belts:
                    d = math.dist((e.x, e.y, e.z), (wx, wy, wz))
                    if best is None or d < best[0]:
                        best = (d, e)
                assert best is not None
                d, e = best
                r = run_of[e.index]
                print(
                    f"  area {area.area} ({label}) -> world ({wx:.2f},{wy:.2f},{wz:.2f}); "
                    f"nearest belt#{e.index} ({e.x},{e.y},{e.z}) run {r} "
                    f"items={sorted(run_items[r]) or '[]'} dist={d:.3f}"
                )
        print()


if __name__ == "__main__":
    main()
