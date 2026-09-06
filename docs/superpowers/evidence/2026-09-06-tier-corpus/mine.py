"""Mine the solved corpus for recurring recipe clusters -- the block candidates.

Three passes:

1. **Co-occurrence.** For every ordered-insensitive recipe pair, how many specs
   contain both, how often they are directly adjacent (one feeds the other),
   and how often they merely share an input item.  Adjacency is the signal that
   matters for a physical block: two recipes that share an ore but never touch
   want a shared bus, not a shared block.

2. **Shared ingredients.** Per item: how many distinct recipes across the
   corpus consume it, and in how many specs TWO OR MORE recipes consume it at
   once.  The second number is the one that argues for a bus.

3. **Frequent connected subgraphs, size 2-6.**  Node labels are recipe ids and
   are unique inside a spec, so an induced subgraph is fully identified by its
   node set -- the canonical string is just the sorted recipe ids and no
   isomorphism test is needed.  Enumeration is ESU (Wernicke's
   ``EnumerateSubgraphs``) over the undirected projection, run once per DISTINCT
   spec graph (123 of them for 940 specs) and then attributed back to every
   spec carrying that graph.

   A candidate is reported as **closed** when there is no single recipe that
   attaches to it in EVERY spec that supports it.  If such a recipe exists, the
   cluster is never seen without that neighbour, so the cluster alone is not the
   block -- the cluster plus the neighbour is.  Without this test the top list is
   drowned in the 2- to 6-node fragments of one big always-together cluster
   (2825 of them at this support floor, against 35 closed).  Note the test is
   run against the size-6 enumeration but is NOT limited by it: the extension
   candidate is read from the spec graph, so a size-6 set that always sits under
   a 7th recipe is correctly rejected.

Position on the chain is a dataset-level *depth*: an item with no buildable
producer is depth 0 (belted in), a recipe is 1 + the max depth of its inputs,
and an item is the min over its producers.  Low mean depth is the ore end
(trunk); high is the product end.
"""

from __future__ import annotations

import collections
import itertools
import json
import statistics
from pathlib import Path

from tiers import Tiers

from flab2bp.lab.data import load_vendored
from flab2bp.lab.schema import Dataset

HERE = Path(__file__).parent
MAX_SUBGRAPH = 6
MIN_SUBGRAPH = 2
#: Support floor, chosen so the closed top list lands in the 20-50 band the
#: brief asks for.  Measured, not guessed -- see README.
MIN_SUPPORT_SPECS = 25


def recipe_depth(data: Dataset, tiers: Tiers) -> tuple[dict[str, int], dict[str, int]]:
    """Chain depth for every recipe and item over the full (tier 6) recipe set.

    Fixpoint rather than a topological pass because the DSP recipe graph has
    genuine cycles (``reforming-refine`` consumes and produces refined oil), so
    a topological order does not exist.
    """
    excluded = set(data.default_recipe_excluded) | set(tiers.tech_ids)
    recipes = [recipe for recipe in data.recipes if recipe.id not in excluded]
    producers: dict[str, list[str]] = collections.defaultdict(list)
    by_id = {recipe.id: recipe for recipe in recipes}
    for recipe in recipes:
        for item_id in recipe.outputs:
            producers[item_id].append(recipe.id)

    item_depth: dict[str, int] = {}
    recipe_d: dict[str, int] = {rid: 0 for rid in by_id}
    for _ in range(64):
        changed = False
        for item_id in {i for r in recipes for i in (*r.inputs, *r.outputs)}:
            if item_id not in producers:
                value = 0
            else:
                value = min(recipe_d[rid] for rid in producers[item_id])
            if item_depth.get(item_id) != value:
                item_depth[item_id] = value
                changed = True
        for rid, recipe in by_id.items():
            value = 1 + max((item_depth.get(i, 0) for i in recipe.inputs), default=0)
            if recipe_d[rid] != value:
                recipe_d[rid] = value
                changed = True
        if not changed:
            break
    return recipe_d, item_depth


def enumerate_connected(
    adjacency: dict[str, set[str]], order: list[str], max_size: int
) -> set[frozenset[str]]:
    """ESU: every connected induced subgraph of size 2..max_size, once each."""
    index = {node: position for position, node in enumerate(order)}
    found: set[frozenset[str]] = set()

    def extend(subgraph: list[str], extension: set[str], root: str) -> None:
        if len(subgraph) >= MIN_SUBGRAPH:
            found.add(frozenset(subgraph))
        if len(subgraph) == max_size:
            return
        pool = set(extension)
        while pool:
            node = pool.pop()
            # ESU's exclusive neighbourhood: only neighbours of `node` that are
            # not already adjacent to the current subgraph, and that come after
            # the root, may join -- this is what makes each set appear once.
            neighbourhood = set(subgraph) | {
                other for member in subgraph for other in adjacency[member]
            }
            fresh = {
                other
                for other in adjacency[node]
                if other not in neighbourhood and index[other] > index[root]
            }
            extend([*subgraph, node], pool | fresh, root)

    for root in order:
        extension = {node for node in adjacency[root] if index[node] > index[root]}
        extend([root], extension, root)
    return found


def main() -> int:
    data = load_vendored()
    tiers = Tiers(data)
    depth, item_depth = recipe_depth(data, tiers)
    specs = [
        json.loads(line)
        for line in (HERE / "solves.jsonl").read_text().splitlines()
        if line.strip()
    ]
    ok = [spec for spec in specs if spec["ok"]]
    total = len(ok)

    # ---- pass 1: co-occurrence -------------------------------------------
    recipe_specs: collections.Counter[str] = collections.Counter()
    recipe_targets: dict[str, set[str]] = collections.defaultdict(set)
    pair_specs: collections.Counter[tuple[str, str]] = collections.Counter()
    pair_adjacent: collections.Counter[tuple[str, str]] = collections.Counter()
    pair_shared_input: collections.Counter[tuple[str, str]] = collections.Counter()
    item_consumers: dict[str, set[str]] = collections.defaultdict(set)
    item_multi_consumer_specs: collections.Counter[str] = collections.Counter()
    item_crossing_specs: collections.Counter[str] = collections.Counter()

    inputs_of = {recipe.id: frozenset(recipe.inputs) for recipe in data.recipes}

    for spec in ok:
        names = sorted({group["recipe"] for group in spec["groups"]})
        for name in names:
            recipe_specs[name] += 1
            recipe_targets[name].add(spec["target"])
        adjacency = {tuple(sorted((edge["from"], edge["to"]))) for edge in spec["edges"]}
        for left, right in itertools.combinations(names, 2):
            pair_specs[(left, right)] += 1
            if (left, right) in adjacency:
                pair_adjacent[(left, right)] += 1
            if inputs_of.get(left, frozenset()) & inputs_of.get(right, frozenset()):
                pair_shared_input[(left, right)] += 1
        consumers: collections.Counter[str] = collections.Counter()
        for name in names:
            for item_id in inputs_of.get(name, ()):
                item_consumers[item_id].add(name)
                consumers[item_id] += 1
        for item_id, count in consumers.items():
            if count >= 2:
                item_multi_consumer_specs[item_id] += 1
        for edge in spec["edges"]:
            item_crossing_specs[edge["item"]] += 1

    # ---- pass 2: subgraph enumeration over DISTINCT spec graphs ----------
    by_graph: dict[tuple[frozenset[str], frozenset[tuple[str, str]]], list[dict]] = {}
    for spec in ok:
        key = (
            frozenset(group["recipe"] for group in spec["groups"]),
            frozenset(tuple(sorted((edge["from"], edge["to"]))) for edge in spec["edges"]),
        )
        by_graph.setdefault(key, []).append(spec)

    support: collections.Counter[frozenset[str]] = collections.Counter()
    sub_tiers: dict[frozenset[str], set[int]] = collections.defaultdict(set)
    sub_targets: dict[frozenset[str], set[str]] = collections.defaultdict(set)
    sub_kinds: dict[frozenset[str], collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    machines: dict[frozenset[str], dict[str, list[int]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )

    #: For each subgraph, the recipes that attach to it in EVERY supporting
    #: spec.  Intersected as graphs are visited; ``None`` means "not seen yet".
    always_attached: dict[frozenset[str], set[str] | None] = {}
    spec_members: dict[frozenset[str], set[str]] = collections.defaultdict(set)

    for (nodes, edge_set), members in by_graph.items():
        adjacency: dict[str, set[str]] = {node: set() for node in nodes}
        for left, right in edge_set:
            if left in adjacency and right in adjacency:
                adjacency[left].add(right)
                adjacency[right].add(left)
        order = sorted(nodes)
        subgraphs = enumerate_connected(adjacency, order, MAX_SUBGRAPH)
        for subgraph in subgraphs:
            attached = {
                other for name in subgraph for other in adjacency[name] if other not in subgraph
            }
            prior = always_attached.get(subgraph, "unset")  # type: ignore[assignment]
            always_attached[subgraph] = (
                attached if prior == "unset" else (prior & attached)  # type: ignore[operator]
            )
        for spec in members:
            counts = {group["recipe"]: group["machines"] for group in spec["groups"]}
            for subgraph in subgraphs:
                support[subgraph] += 1
                sub_tiers[subgraph].add(spec["tier"])
                sub_targets[subgraph].add(spec["target"])
                sub_kinds[subgraph][spec["kind"]] += 1
                spec_members[subgraph].add(spec["label"])
                bucket = machines[subgraph]
                for name in subgraph:
                    bucket[name].append(counts[name])

    frequent = {
        subgraph: count for subgraph, count in support.items() if count >= MIN_SUPPORT_SPECS
    }
    closed = {subgraph for subgraph in frequent if not always_attached.get(subgraph)}

    def describe(subgraph: frozenset[str]) -> dict[str, object]:
        members = sorted(subgraph)
        inner = {item_id for name in members for item_id in data.recipe(name).outputs}
        return {
            "recipes": members,
            "size": len(members),
            "specs": frequent[subgraph],
            "spec_share": round(frequent[subgraph] / total, 3),
            "distinct_targets": len(sub_targets[subgraph]),
            "tiers": sorted(sub_tiers[subgraph]),
            "tier_span": max(sub_tiers[subgraph]) - min(sub_tiers[subgraph]) + 1,
            "kinds": dict(sub_kinds[subgraph]),
            "closed": subgraph in closed,
            "mean_depth": round(statistics.mean(depth.get(n, 0) for n in members), 2),
            "depth_range": [
                min(depth.get(n, 0) for n in members),
                max(depth.get(n, 0) for n in members),
            ],
            "end": "trunk"
            if statistics.mean(depth.get(n, 0) for n in members) <= 2.5
            else "product",
            "machines": {
                name: {
                    "min": min(machines[subgraph][name]),
                    "median": int(statistics.median(machines[subgraph][name])),
                    "max": max(machines[subgraph][name]),
                }
                for name in members
            },
            "fan_in": {
                name: {
                    "inputs": sorted(inputs_of.get(name, ())),
                    "from_outside_block": sorted(inputs_of.get(name, set()) - inner),
                }
                for name in members
            },
            "internal_edges": sorted(
                f"{left}->{right}"
                for left in members
                for right in members
                if left != right and set(data.recipe(left).outputs) & set(inputs_of.get(right, ()))
            ),
        }

    ranked = sorted(
        (describe(subgraph) for subgraph in closed),
        key=lambda entry: (
            -int(entry["distinct_targets"]),
            -int(entry["specs"]),
            -int(entry["size"]),
        ),
    )

    # Greedy set cover: which blocks, in order, cover the most SPECS not yet
    # covered by an earlier pick.  This is the "what would a block library
    # actually buy me" number, as opposed to raw frequency.
    covered: set[str] = set()
    cover: list[dict[str, object]] = []
    pool = set(closed)
    while pool and len(cover) < 15:
        best = max(pool, key=lambda s: (len(spec_members[s] - covered), len(s)))
        gain = len(spec_members[best] - covered)
        if gain == 0:
            break
        covered |= spec_members[best]
        pool.discard(best)
        cover.append(
            {
                "recipes": sorted(best),
                "new_specs_covered": gain,
                "cumulative_specs": len(covered),
                "cumulative_share": round(len(covered) / total, 3),
            }
        )

    payload = {
        "corpus": {
            "rows": len(specs),
            "solved": total,
            "refused": len(specs) - total,
            "distinct_spec_graphs": len(by_graph),
            "min_support_specs": MIN_SUPPORT_SPECS,
            "subgraph_sizes": [MIN_SUBGRAPH, MAX_SUBGRAPH],
        },
        "recipe_frequency": [
            {
                "recipe": name,
                "specs": count,
                "spec_share": round(count / total, 3),
                "distinct_targets": len(recipe_targets[name]),
                "depth": depth.get(name, 0),
            }
            for name, count in recipe_specs.most_common()
        ],
        "shared_ingredients": [
            {
                "item": item_id,
                "consuming_recipes_in_corpus": len(consumers),
                "specs_with_2plus_consumers": item_multi_consumer_specs.get(item_id, 0),
                "internal_edges_carrying_it": item_crossing_specs.get(item_id, 0),
                "depth": item_depth.get(item_id, 0),
            }
            for item_id, consumers in sorted(
                item_consumers.items(),
                # The item id breaks ties: without it the order falls through to
                # frozenset iteration order, which PYTHONHASHSEED randomises and
                # which made this one section of the output non-reproducible.
                key=lambda kv: (-item_multi_consumer_specs.get(kv[0], 0), -len(kv[1]), kv[0]),
            )
        ],
        "top_pairs": [
            {
                "pair": [left, right],
                "specs": count,
                "adjacent_specs": pair_adjacent[(left, right)],
                "shared_input_specs": pair_shared_input[(left, right)],
                "adjacency_rate": round(pair_adjacent[(left, right)] / count, 3),
            }
            for (left, right), count in pair_specs.most_common(200)
        ],
        "block_candidates": ranked,
        "greedy_cover": cover,
    }
    (HERE / "mining.json").write_text(json.dumps(payload, indent=1) + "\n")

    print(f"specs={total} distinct graphs={len(by_graph)}")
    print(
        f"frequent subgraphs (>= {MIN_SUPPORT_SPECS} specs): {len(frequent)}, closed: {len(closed)}"
    )
    print("top 12 closed block candidates by distinct targets:")
    for entry in ranked[:12]:
        print(
            f"  {entry['distinct_targets']:>3} targets / {entry['specs']:>4} specs "
            f"T{entry['tiers'][0]}-{entry['tiers'][-1]} {entry['end']:<7} "
            f"{'+'.join(entry['recipes'])}"  # type: ignore[arg-type]
        )
    print("greedy cover:")
    for entry in cover[:8]:
        recipes = "+".join(entry["recipes"])  # type: ignore[arg-type]
        print(f"  +{entry['new_specs_covered']:>4} -> {entry['cumulative_share']}  {recipes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
