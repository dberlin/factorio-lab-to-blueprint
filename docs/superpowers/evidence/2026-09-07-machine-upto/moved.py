"""Measure rates-only moves and join them to the complete 72-cell layout gate.

Run from the candidate checkout after review. Power is installed machine nameplate
usage in dataset kW, not measured factory draw (sorters/coaters are excluded).
No layout is solved here, and missing layout evidence is an error, not a zero.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from fractions import Fraction
from pathlib import Path

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates
from flab2bp.rates.machine_choice import MachineRank
from flab2bp.spec import BuildSpec

from run_gate import POLICIES, STRATEGIES, URL_IDS, read_rows


def invariant_view(spec: BuildSpec) -> dict[str, object]:
    return {
        "groups": [
            (group.recipe_id, group.count, group.proliferator_mode,
             group.inputs_per_machine, group.outputs_per_machine)
            for group in spec.groups
        ],
        "inputs": spec.external_inputs,
        "outputs": spec.outputs,
        "surplus": spec.surplus_outputs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--layouts", type=Path)
    args = parser.parse_args()
    data = canonicalize_dataset(load_vendored())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    rows = []
    for entry in URL_CORPUS:
        if entry.url_id not in URL_IDS:
            continue
        arms = {
            rank: build_candidates(
                data, parse_url(entry.url), machine_rank=rank,
                candidate_policies=DEFAULT_CANDIDATE_POLICIES,
            ).candidates
            for rank in MachineRank
        }
        for index, policy in enumerate(POLICIES):
            exact = arms[MachineRank.EXACT][index]
            upto = arms[MachineRank.UP_TO][index]
            if invariant_view(exact) != invariant_view(upto):
                raise RuntimeError(f"Invariant U failed: {entry.url_id}/{policy}")
            for rank in MachineRank:
                spec = arms[rank][index]
                unknown = sorted({
                    group.machine_item_id for group in spec.groups
                    if data.machine(group.machine_item_id).usage is None
                })
                power = None if unknown else str(sum((
                    group.count * data.machine(group.machine_item_id).usage
                    for group in spec.groups
                ), Fraction(0)))
                rows.append({
                    "commit": commit, "url_id": entry.url_id, "policy": policy,
                    "spec_index": index, "machine_rank": rank.value,
                    "machines": spec.machine_count, "invariant_u": True,
                    "machine_power_kw": power, "unknown_power_machines": unknown,
                    "machine_moves": [move.model_dump() for move in spec.machine_moves],
                })
    if len(rows) != 72:
        raise RuntimeError(f"expected 72 rate records, got {len(rows)}")
    args.out.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    if args.layouts is not None:
        metrics = {(row["machine_rank"], row["url_id"], row["spec_index"]): row for row in rows}
        expected = {(strategy, url_id, index) for strategy in STRATEGIES
                    for url_id in URL_IDS for index in range(3)}
        layouts = {}
        for arm in ("base", "exact", "up-to"):
            records = read_rows(args.layouts / f"{arm}.jsonl")
            mapped = {(row["strategy"], row["url_id"], row["spec_index"]): row for row in records}
            if len(records) != 72 or set(mapped) != expected:
                raise RuntimeError(f"{arm}: incomplete or duplicate 72-cell layout round")
            layouts[arm] = mapped
        print("| URL | policy | placer | base/exact/up-to status | area | belts | exact/up-to machines | machine kW | moves |")
        print("|---|---|---|---|---|---|---|---|---|")
        for strategy, url_id, index in sorted(expected):
            key = (strategy, url_id, index)
            cells = [layouts[arm][key] for arm in ("base", "exact", "up-to")]
            pair = [metrics[(arm, url_id, index)] for arm in ("exact", "up-to")]
            values = ["/".join(str(row.get(field, "missing")) for row in cells)
                      for field in ("status", "area", "belt_tiles")]
            counts = "/".join(str(row["machines"]) for row in pair)
            power = "/".join(str(row["machine_power_kw"]) for row in pair)
            moves = "; ".join(f"{move['recipe_id']}: {move['from_machine']} → {move['to_machine']}"
                              for move in pair[1]["machine_moves"]) or "none"
            print(f"| {url_id} | {POLICIES[index]} | {strategy} | "
                  f"{' | '.join(values)} | {counts} | {power} | {moves} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
