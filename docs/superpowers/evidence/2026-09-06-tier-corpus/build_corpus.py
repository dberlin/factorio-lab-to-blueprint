"""Emit one FactorioLab URL per (tier, target, rate, policy) cell.

Three target families, chosen to match how DSP is actually played:

* **buildings** at 1/min -- "keep one of these rolling off the line".  Every
  item in dataset category ``buildings``/``buildings-alt`` that some recipe
  produces.
* **research matrices** at 60/min and 600/min -- the two canonical lab feeds,
  and the 10x variant that shows which recipes stay singleton and which
  multiply.
* **components** at 60/min -- the trunk.  Every item in dataset category
  ``components``.  Only the no-proliferator policy, to keep the sweep bounded.

The tier restriction cannot be written into a bare URL.  ``lab/url.py`` encodes
the excluded-recipe set under ``rex`` and the researched-technology set under
``tre``, both as ``parse_subset`` payloads indexed against the mod hash tables,
so a hand-written bare URL cannot carry either.  It is therefore recorded in
``restrictions.json`` and applied to the parsed ``LabRequest`` by
``solve_corpus.py`` via ``dataclasses.replace``.

Worth stating plainly, because it is a trap: **the rate solver never reads
``researched_technology_ids``**.  A repo-wide search finds that field used only
in ``lab/techs.py``, which derives belt/sorter altitude rules for the LAYOUT
stage.  What actually constrains ``rates.solve`` is
``solve.py::_excluded_recipes``, which reads ``request.excluded_recipe_ids``
(and treats a present set as authoritative and whole, not as a delta).  So the
tier gate here is an exclusion set, and the researched set is carried alongside
only so the sidecar describes a complete save.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from tiers import LADDER_TIERS, TIER_NAME, Tiers

from flab2bp.lab.data import load_vendored
from flab2bp.lab.schema import Dataset

HERE = Path(__file__).parent

#: A bare FactorioLab URL: ``o=<item>*<value>`` with the defaults
#: ``ObjectiveUnit.Items`` / ``ObjectiveType.Output`` and
#: ``DisplayRate.PerMinute`` (``lab/url.py::_parse_objectives``,
#: ``rates/solve.py::target_rates``), so the value reads directly as items/min.
URL_BASE = "https://factoriolab.github.io/dsp/list"

#: The proliferator production recipes, in tier order.  A tier that can build
#: one can spray, so ``all-products`` is a real option there.
PROLIFERATOR_RECIPES = ("proliferator-1", "proliferator-2", "proliferator-3")

TIER_MODULE_ID = {
    1: "proliferator-1-products",
    2: "proliferator-2-products",
    3: "proliferator-3-products",
}


def make_url(target: str, rate: int) -> str:
    return f"{URL_BASE}?o={target}*{rate}&v=11"


def proliferator_tier_at(tiers: Tiers, tier: int) -> int:
    """Highest proliferator mark researchable at ``tier``; 0 for none."""
    best = 0
    for mark, recipe_id in enumerate(PROLIFERATOR_RECIPES, start=1):
        if tiers.recipe.get(recipe_id, 99) <= tier:
            best = mark
    return best


def machine_rank_for(data: Dataset, tiers: Tiers, tier: int) -> list[str]:
    """Best-first rank over the machines this tier can build.

    ``rates/adjust.py::select_machine`` walks the rank and returns the first id
    that appears in ``recipe.producers``, falling back to ``producers[0]``.
    With no rank at all, a tier-0 save would silently be given
    ``assembling-machine-3``; the rank is what stops that.  Ordering globally by
    speed is safe because the walk only ever compares ids inside one recipe's
    own producer set.
    """
    available = [
        item
        for item in data.items
        if item.machine is not None and tiers.item.get(item.id, 99) <= tier
    ]
    available.sort(key=lambda item: (-float(item.machine.speed or 0), item.id))
    return [item.id for item in available]


def restrictions_for(data: Dataset, tiers: Tiers, tier: int) -> dict[str, object]:
    excluded = (
        set(data.default_recipe_excluded)
        | {recipe_id for recipe_id, t in tiers.recipe.items() if t > tier}
        # Research recipes consume matrices and produce a technology token that
        # never flows on a belt.  They are columns the LP has no business
        # pricing, at any tier.
        | set(tiers.tech_ids)
    )
    researched = {tech_id for tech_id, t in tiers.tech.items() if t <= tier}
    return {
        "tier": tier,
        "tier_name": TIER_NAME[tier],
        "excluded_recipe_ids": sorted(excluded),
        "researched_technology_ids": sorted(researched),
        "machine_rank_ids": machine_rank_for(data, tiers, tier),
        "proliferator_mark": proliferator_tier_at(tiers, tier),
    }


def rows(data: Dataset, tiers: Tiers) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for tier in LADDER_TIERS:
        mark = proliferator_tier_at(tiers, tier)
        policies = ["no-proliferator"] + (["all-products"] if mark else [])
        plans: list[tuple[str, str, int, list[str]]] = []
        for building_id, t in sorted(tiers.buildings.items()):
            if t <= tier:
                plans.append(("building", building_id, 1, policies))
        for matrix_id, t in sorted(tiers.matrices.items()):
            if t <= tier:
                plans.append(("matrix", matrix_id, 60, policies))
                plans.append(("matrix10x", matrix_id, 600, policies))
        for component_id, t in sorted(tiers.components.items()):
            if t <= tier:
                plans.append(("component", component_id, 60, ["no-proliferator"]))
        for kind, target, rate, kind_policies in plans:
            # Dark Fog items have no normal DSP catalog identity and
            # ``rates.build_candidates`` refuses them outright, so they are not
            # corpus targets even though ``tiers.json`` scores them.
            if target.startswith("df-"):
                continue
            for policy in kind_policies:
                out.append(
                    {
                        "tier": tier,
                        "kind": kind,
                        "label": f"T{tier}/{kind}/{target}@{rate}/{policy}",
                        "target": target,
                        "target_tier": tiers.item[target],
                        "rate_per_min": rate,
                        "policy": policy,
                        "proliferator_mark": mark if policy != "no-proliferator" else 0,
                        "url": make_url(target, rate),
                    }
                )
    return out


def main() -> int:
    data = load_vendored()
    tiers = Tiers(data)
    corpus = rows(data, tiers)
    fields = [
        "tier",
        "kind",
        "label",
        "target",
        "target_tier",
        "rate_per_min",
        "policy",
        "proliferator_mark",
        "url",
    ]
    with (HERE / "corpus.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(corpus)
    restrictions = {str(tier): restrictions_for(data, tiers, tier) for tier in LADDER_TIERS}
    (HERE / "restrictions.json").write_text(json.dumps(restrictions, indent=1) + "\n")

    per_tier: dict[int, int] = {}
    for row in corpus:
        tier = int(row["tier"])  # type: ignore[arg-type]
        per_tier[tier] = per_tier.get(tier, 0) + 1
    print(f"corpus.tsv: {len(corpus)} rows")
    print("  per tier: " + "  ".join(f"T{k}={v}" for k, v in sorted(per_tier.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
