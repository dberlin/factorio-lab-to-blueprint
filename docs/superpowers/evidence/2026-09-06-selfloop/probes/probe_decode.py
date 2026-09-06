"""Throwaway probe: decode an emitted blueprint and trace one item's belt runs.

Usage:
    uv run python .../probe_decode.py <blueprint.txt> [item-name-substring ...]

Prints, for the decoded blueprint:
  * a census of buildings by catalog name;
  * every belt RUN (a maximal chain of belts linked by output_obj_idx), the
    items its attached sorters carry, whether the run starts/ends at the
    blueprint boundary, and whether it closes on itself;
  * every machine with its recipe and its input/output sorters, flagging any
    machine with two or more INPUT sorters drawing off the same belt run;
  * every Spray Coater and the belt run it sits on.
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


def recipe_name(recipe: int) -> str:
    return _RECIPE_NAMES.get(recipe, f"recipe#{recipe}")


def main() -> None:
    path = Path(sys.argv[1])
    text = path.read_text().strip()
    bp = decode(text)
    b = bp.buildings
    by_index = {x.index: x for x in b}

    print(f"== {path.name}: {len(b)} buildings, hash_valid={bp.hash_valid}")
    print("short_desc:", bp.header.short_desc)
    print("description:", bp.header.description)
    print()

    census: dict[str, int] = defaultdict(int)
    for x in b:
        census[name_of(x.item_id)] += 1
    print("== census ==")
    for n, c in sorted(census.items(), key=lambda kv: -kv[1]):
        print(f"  {c:5d}  {n}")
    print()

    belts = [x for x in b if is_belt(x.item_id)]
    sorters = [x for x in b if is_sorter(x.item_id)]
    machines = [x for x in b if not is_belt(x.item_id) and not is_sorter(x.item_id)]

    # --- belt runs -------------------------------------------------------
    belt_ids = {x.index for x in belts}
    succ: dict[int, int] = {}
    pred: dict[int, list[int]] = defaultdict(list)
    for x in belts:
        if x.output_obj_idx in belt_ids:
            succ[x.index] = x.output_obj_idx
            pred[x.output_obj_idx].append(x.index)

    run_of: dict[int, int] = {}
    runs: list[list[int]] = []
    heads = [x.index for x in belts if not pred[x.index]]
    seen: set[int] = set()
    for h in heads:
        chain = []
        cur: int | None = h
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            cur = succ.get(cur)
        runs.append(chain)
    # leftover belts form cycles
    for x in belts:
        if x.index not in seen:
            chain = []
            cur = x.index
            while cur not in seen:
                seen.add(cur)
                chain.append(cur)
                cur = succ.get(cur)
                if cur is None:
                    break
            if chain:
                runs.append(chain)
    for i, chain in enumerate(runs):
        for idx in chain:
            run_of[idx] = i

    # --- sorter attachments ---------------------------------------------
    # A sorter has input_obj_idx (source) and output_obj_idx (sink).
    run_items: dict[int, set[str]] = defaultdict(set)
    machine_in: dict[int, list] = defaultdict(list)
    machine_out: dict[int, list] = defaultdict(list)
    coater_run: dict[int, int | None] = {}

    for s in sorters:
        item = name_of(s.filter_id) if s.filter_id else "(no filter)"
        src = s.input_obj_idx
        dst = s.output_obj_idx
        if src in run_of:
            run_items[run_of[src]].add(item)
        if dst in run_of:
            run_items[run_of[dst]].add(item)
        if dst in by_index and dst not in run_of:
            machine_in[dst].append(s)
        if src in by_index and src not in run_of:
            machine_out[src].append(s)

    print(f"== {len(runs)} belt runs ==")
    for i, chain in enumerate(runs):
        first = by_index[chain[0]]
        last = by_index[chain[-1]]
        closes = last.output_obj_idx in belt_ids and run_of.get(last.output_obj_idx) == i
        tail_target = last.output_obj_idx
        tail_desc = "TERMINATES"
        if tail_target in run_of:
            tail_desc = f"-> run {run_of[tail_target]}"
        elif tail_target in by_index:
            tail_desc = f"-> {name_of(by_index[tail_target].item_id)}#{tail_target}"
        print(
            f"  run {i:3d}: {len(chain):3d} belts "
            f"({first.x:.1f},{first.y:.1f}) -> ({last.x:.1f},{last.y:.1f}) "
            f"items={sorted(run_items[i]) or '[]'} "
            f"{'CYCLE ' if closes else ''}{tail_desc}"
        )
    print()

    print("== machines and their sorters ==")
    for m in sorted(machines, key=lambda x: (x.y, x.x)):
        if is_belt(m.item_id) or is_sorter(m.item_id):
            continue
        ins = machine_in.get(m.index, [])
        outs = machine_out.get(m.index, [])
        if not ins and not outs:
            continue
        recipe = m.recipe_id
        rname = recipe_name(recipe) if recipe else "-"
        in_runs: dict[int, list[str]] = defaultdict(list)
        for s in ins:
            r = run_of.get(s.input_obj_idx)
            in_runs[r if r is not None else -1].append(
                name_of(s.filter_id) if s.filter_id else "(no filter)"
            )
        shared = {r: items for r, items in in_runs.items() if r >= 0 and len(items) >= 2}
        flag = "  <<< SHARED-INPUT-RUN" if shared else ""
        print(
            f"  {name_of(m.item_id)}#{m.index} at ({m.x:.1f},{m.y:.1f}) recipe={rname} "
            f"in_sorters={len(ins)} out_sorters={len(outs)}{flag}"
        )
        for r, items in sorted(in_runs.items()):
            print(f"      from run {r}: {sorted(items)}")
        for s in outs:
            r = run_of.get(s.output_obj_idx)
            print(
                f"      out -> run {r}: "
                f"{name_of(s.filter_id) if s.filter_id else '(no filter)'}"
            )
    print()

    print("== spray coaters ==")
    for m in machines:
        if m.item_id != catalog.SPRAY_COATER_ID:
            continue
        src = run_of.get(m.input_obj_idx)
        dst = run_of.get(m.output_obj_idx)
        print(
            f"  coater#{m.index} at ({m.x:.1f},{m.y:.1f}) "
            f"in_obj={m.input_obj_idx}(run {src}) out_obj={m.output_obj_idx}(run {dst})"
        )


if __name__ == "__main__":
    main()
