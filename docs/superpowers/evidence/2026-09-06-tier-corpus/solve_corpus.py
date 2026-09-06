"""Run the RATE solve for every corpus row and cache the result as JSONL.

No layout, no ``scripts/audit.py``, no harness: ``rates.solve`` only.  Each row
takes 0.02-0.2 s, so the whole corpus is a couple of minutes single-threaded.

Policy mapping copies ``rates/candidates.py::_build_candidates_canonical``
exactly, so what is cached here is what the real pipeline would have solved:

* ``no-proliferator`` -> ``solve(..., mode_policy=ProliferatorMode.NONE)``
* ``all-products``    -> ``solve(..., tier=<mark>, mode_policy=PRODUCTS)``,
  dropped when its machine count exceeds ``_RUNAWAY_FACTOR`` (4) times the
  unproliferated baseline, which is that module's guard against the
  ``reforming-refine`` / ``plasma-refining`` self-feeding loop.

The tier gate is applied by replacing ``excluded_recipe_ids`` and
``machine_rank_ids`` on the parsed ``LabRequest`` (see ``build_corpus.py`` for
why it cannot live in the URL).

Each record carries the recipe set, per-recipe machine counts, and the item
flow graph as producer->consumer edges keyed by the item that crosses them.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import time
from pathlib import Path

from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import LabRequest, parse_url
from flab2bp.rates import InfeasibleError, RateSolution, UnsupportedObjectiveError, solve
from flab2bp.rates.adjust import ProliferatorTier
from flab2bp.spec import ProliferatorMode

HERE = Path(__file__).parent
RUNAWAY_FACTOR = 4  # rates/candidates.py::_RUNAWAY_FACTOR
TIME_LIMIT_S = 20.0

MARK_TO_TIER = {
    1: ProliferatorTier.MK1,
    2: ProliferatorTier.MK2,
    3: ProliferatorTier.MK3,
}


def restricted(request: LabRequest, restriction: dict[str, object]) -> LabRequest:
    return dataclasses.replace(
        request,
        excluded_recipe_ids=set(restriction["excluded_recipe_ids"]),  # type: ignore[arg-type]
        researched_technology_ids=set(restriction["researched_technology_ids"]),  # type: ignore[arg-type]
        machine_rank_ids=list(restriction["machine_rank_ids"]),  # type: ignore[arg-type]
    )


def edges(solution: RateSolution) -> list[dict[str, object]]:
    """Producer -> consumer, one entry per (item, producer, consumer) triple."""
    producers: dict[str, list[int]] = {}
    for index, group in enumerate(solution.groups):
        for item_id in group.outputs:
            producers.setdefault(item_id, []).append(index)
    out: list[dict[str, object]] = []
    for index, group in enumerate(solution.groups):
        for item_id, rate in group.inputs.items():
            for source in producers.get(item_id, ()):
                if source == index:
                    continue  # a recipe feeding itself is not a block edge
                out.append(
                    {
                        "from": solution.groups[source].recipe_id,
                        "to": group.recipe_id,
                        "item": item_id,
                        "consumed_per_s": float(rate),
                    }
                )
    return out


def encode(solution: RateSolution) -> dict[str, object]:
    return {
        "groups": [
            {
                "recipe": group.recipe_id,
                "machine": group.machine_item_id,
                "machines": group.machines,
                "exact_machines": float(group.exact_machines),
                "mode": group.mode.value if hasattr(group.mode, "value") else str(group.mode),
                "inputs": {k: float(v) for k, v in sorted(group.inputs.items())},
                "outputs": {k: float(v) for k, v in sorted(group.outputs.items())},
            }
            for group in solution.groups
        ],
        "edges": edges(solution),
        "external_inputs": {k: float(v) for k, v in sorted(solution.external_inputs.items())},
        "outputs": {k: float(v) for k, v in sorted(solution.outputs.items())},
        "machine_count": solution.machine_count,
        "total_area": solution.total_area,
    }


def main() -> int:
    data = load_vendored()
    restrictions = json.loads((HERE / "restrictions.json").read_text())
    with (HERE / "corpus.tsv").open(newline="") as handle:
        corpus = list(csv.DictReader(handle, delimiter="\t"))

    # The unproliferated solve for a cell is both a corpus row in its own right
    # and the runaway reference for that cell's all-products row, so it is
    # cached by key rather than solved twice.
    baseline_machines: dict[tuple[str, str, str], int] = {}
    solved = refused = 0
    started = time.time()
    with (HERE / "solves.jsonl").open("w") as out:
        for row in corpus:
            tier = row["tier"]
            key = (tier, row["target"], row["rate_per_min"])
            record: dict[str, object] = {
                "label": row["label"],
                "tier": int(tier),
                "kind": row["kind"],
                "target": row["target"],
                "target_tier": int(row["target_tier"]),
                "rate_per_min": int(row["rate_per_min"]),
                "policy": row["policy"],
                "url": row["url"],
            }
            request = restricted(parse_url(row["url"]), restrictions[tier])
            mark = int(row["proliferator_mark"])
            began = time.time()
            try:
                if row["policy"] == "no-proliferator" or mark == 0:
                    solution = solve(
                        data,
                        request,
                        mode_policy=ProliferatorMode.NONE,
                        time_limit_s=TIME_LIMIT_S,
                    )
                    baseline_machines[key] = solution.machine_count
                else:
                    solution = solve(
                        data,
                        request,
                        tier=MARK_TO_TIER[mark],
                        mode_policy=ProliferatorMode.PRODUCTS,
                        time_limit_s=TIME_LIMIT_S,
                    )
                    reference = baseline_machines.get(key, 0)
                    if reference > 0 and solution.machine_count > reference * RUNAWAY_FACTOR:
                        raise InfeasibleError(
                            f"runaway proliferated solve: {solution.machine_count:,} machines "
                            f"against an unproliferated baseline of {reference:,}"
                        )
            except (
                InfeasibleError,
                UnsupportedObjectiveError,
                KeyError,
                ValueError,
                AssertionError,
                ZeroDivisionError,
            ) as error:
                refused += 1
                record["ok"] = False
                record["refusal"] = f"{type(error).__name__}: {error}"
            else:
                solved += 1
                record["ok"] = True
                record.update(encode(solution))
            record["solve_s"] = round(time.time() - began, 4)
            out.write(json.dumps(record) + "\n")
            if (solved + refused) % 100 == 0:
                print(f"  {solved + refused}/{len(corpus)}  {time.time() - started:.0f}s")

    print(f"solves.jsonl: {solved} solved, {refused} refused, {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
