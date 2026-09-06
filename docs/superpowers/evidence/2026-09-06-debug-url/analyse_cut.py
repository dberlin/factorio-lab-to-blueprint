"""Read a dumped (placement, spec) and say WHY ``flow.conservation`` is short.

The finding reports one number.  Every physical edge in ``_lane_balance`` is
capped at total demand, so a shortfall is never a throughput result: it is
always reachability -- some producers cannot reach some consumers.  This prints
the bipartite reachability that the max-flow reduced to a single fraction.
"""

from __future__ import annotations

import argparse
import pickle
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp.dsp import catalog as cat  # noqa: E402
from flab2bp.layout import validate as V  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=Path)
    ap.add_argument("--item", action="append", default=[])
    args = ap.parse_args()

    placement, spec = pickle.loads(args.dump.read_bytes())
    ctx = V._context(
        placement,
        spec,
        ids=V.id_map(spec),
        soft_width=256,
        max_belt_z=cat.DEFAULT_MAX_BELT_Z,
        belt_vertical_construction=True,
    )
    items = V._sorter_items(ctx)
    bs = ctx.placement.buildings
    kinds = ctx.kinds
    physical = (V.Kind.BELT, V.Kind.SPLITTER, V.Kind.PILER)
    n = len(bs)

    makes: dict[int, dict[str, Fraction]] = {}
    needs: dict[int, dict[str, Fraction]] = {}
    for i, _ in ctx.of_kind(V.Kind.MACHINE):
        group = ctx.group_for(i)
        if group is None:
            continue
        makes[i] = dict(group.outputs_per_machine)
        needs[i] = dict(group.inputs_per_machine)

    for item in args.item:
        producers = sorted(m for m, r in makes.items() if item in r)
        consumers = sorted(m for m, r in needs.items() if item in r)
        # Forward adjacency over physical cargo carriers only.
        adj: dict[object, set[object]] = defaultdict(set)
        for index, belt in ctx.of_kind(V.Kind.BELT):
            onward = belt.output_obj
            if onward is not None and 0 <= onward < n and kinds[onward] in physical:
                adj[index].add(onward)
            up = belt.input_obj
            if up is not None and 0 <= up < n and kinds[up] in (V.Kind.SPLITTER, V.Kind.PILER):
                adj[up].add(index)
        for si, sorter in ctx.of_kind(V.Kind.SORTER):
            moved = items.get(si)
            if moved is not None and moved != item:
                continue
            src, dst = sorter.input_obj, sorter.output_obj
            if src is None or dst is None or not (0 <= src < n) or not (0 <= dst < n):
                continue
            if kinds[src] is V.Kind.MACHINE:
                fs: object = ("P", src)
            elif kinds[src] in physical:
                fs = src
            else:
                continue
            if kinds[dst] is V.Kind.MACHINE:
                fd: object = ("C", dst)
            elif kinds[dst] in physical:
                fd = dst
            else:
                continue
            adj[fs].add(fd)
        for dock in V._port_docks(ctx):
            if kinds[dock.peer] is not V.Kind.MACHINE:
                continue
            moved = bs[dock.belt].carries_item
            if moved is not None and moved != item:
                continue
            if dock.draws:
                adj[("P", dock.peer)].add(dock.belt)
            else:
                adj[dock.belt].add(("C", dock.peer))

        reach: dict[int, set[int]] = {}
        for p in producers:
            seen: set[object] = set()
            stack: list[object] = [("P", p)]
            got: set[int] = set()
            while stack:
                node = stack.pop()
                if node in seen:
                    continue
                seen.add(node)
                if isinstance(node, tuple) and node[0] == "C":
                    got.add(node[1])
                    continue
                stack.extend(adj.get(node, ()))
            reach[p] = got

        groups: dict[frozenset[int], list[int]] = defaultdict(list)
        for p, got in reach.items():
            groups[frozenset(got)].append(p)
        print(f"=== {item}")
        print(f"  producers {len(producers)}  consumers {len(consumers)}")
        supply = sum(makes[p][item] for p in producers)
        demand = sum(needs[c][item] for c in consumers)
        print(f"  supply {supply}  demand {demand}")
        for got, ps in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            served = sum(needs[c][item] for c in got)
            have = sum(makes[p][item] for p in ps)
            print(
                f"  {len(ps):3d} producer(s) (supply {have}) reach "
                f"{len(got):3d} consumer(s) (demand {served})"
            )
            if len(got) < len(consumers):
                print(f"      producers {ps[:8]}  consumers {sorted(got)[:8]}")
        unreached = set(consumers) - {c for got in groups for c in got}
        if unreached:
            print(f"  {len(unreached)} consumer(s) reached by NO producer: {sorted(unreached)[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
