"""Throwaway probe: dump named belt runs tile by tile, plus coater seats.

Usage:
    uv run python .../probe_runs.py <blueprint.txt> <run-index> [<run-index> ...]
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from flab2bp.dsp import catalog
from flab2bp.dsp.codec import decode
from flab2bp.dsp.records import is_belt, is_sorter

_ITEM_NAMES = {v: k for k, v in catalog._item_ids().items()}  # noqa: SLF001 - probe
_RECIPE_NAMES = {v: k for k, v in catalog._recipe_ids().items()}  # noqa: SLF001 - probe


def name_of(item_id: int) -> str:
    return _ITEM_NAMES.get(item_id, f"item#{item_id}")


def main() -> None:
    path = Path(sys.argv[1])
    wanted = {int(a) for a in sys.argv[2:]}
    bp = decode(path.read_text().strip())
    b = bp.buildings
    by_index = {x.index: x for x in b}
    belts = [x for x in b if is_belt(x.item_id)]
    sorters = [x for x in b if is_sorter(x.item_id)]
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

    xs = [x.x for x in b]
    ys = [x.y for x in b]
    print(f"bounds x {min(xs)}..{max(xs)}  y {min(ys)}..{max(ys)}")

    # sorters touching each run
    touching: dict[int, list] = defaultdict(list)
    for s in sorters:
        for other, role in ((s.input_obj_idx, "picks-from"), (s.output_obj_idx, "places-onto")):
            r = run_of.get(other)
            if r is not None:
                touching[r].append((role, s))

    for i in sorted(wanted):
        chain = runs[i]
        print(f"\n=== run {i}: {len(chain)} belts ===")
        for j, idx in enumerate(chain):
            e = by_index[idx]
            marks = []
            for role, s in touching[i]:
                peer = s.output_obj_idx if role == "picks-from" else s.input_obj_idx
                if (role == "picks-from" and s.input_obj_idx == idx) or (
                    role == "places-onto" and s.output_obj_idx == idx
                ):
                    peer_b = by_index.get(peer)
                    peer_name = name_of(peer_b.item_id) if peer_b else "?"
                    peer_recipe = (
                        _RECIPE_NAMES.get(peer_b.recipe_id, "")
                        if peer_b and peer_b.recipe_id
                        else ""
                    )
                    marks.append(
                        f"{role} {name_of(s.filter_id) if s.filter_id else '(nofilter)'} "
                        f"<-> {peer_name}#{peer}{'/' + peer_recipe if peer_recipe else ''}"
                    )
            tail = ""
            if j == len(chain) - 1:
                t = e.output_obj_idx
                tail = (
                    f"  TAIL-> run {run_of[t]}"
                    if t in run_of
                    else (
                        f"  TAIL-> {name_of(by_index[t].item_id)}#{t}"
                        if t in by_index
                        else "  TAIL TERMINATES (open belt end)"
                    )
                )
            head = ""
            if j == 0:
                srcs = [
                    f"{name_of(by_index[p].item_id)}#{p}"
                    for p in range(0)
                ]
                feeders = [
                    x
                    for x in b
                    if x.output_obj_idx == idx and x.index != idx and not is_belt(x.item_id)
                ]
                head = "  HEAD: fed by " + (
                    ", ".join(f"{name_of(f.item_id)}#{f.index}" for f in feeders)
                    if feeders
                    else "NOTHING (open belt head)"
                )
            print(f"   [{j:3d}] belt#{idx} ({e.x:.1f},{e.y:.1f},{e.z:.1f}){head}{tail}")
            for mk in marks:
                print(f"          {mk}")

    print("\n=== spray coaters and the belts under them ===")
    for m in b:
        if m.item_id != catalog.SPRAY_COATER_ID:
            continue
        near = [
            (e, run_of.get(e.index))
            for e in belts
            if abs(e.x - m.x) <= 1.5 and abs(e.y - m.y) <= 1.5
        ]
        print(f"  coater#{m.index} at ({m.x:.1f},{m.y:.1f},{m.z:.1f}) yaw={m.yaw}")
        for e, r in sorted(near, key=lambda t: (t[0].y, t[0].x)):
            print(f"     belt#{e.index} ({e.x:.1f},{e.y:.1f},{e.z:.1f}) run {r}")


if __name__ == "__main__":
    main()
