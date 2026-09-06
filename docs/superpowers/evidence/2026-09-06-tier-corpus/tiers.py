"""Derive a cube-colour tech tier for every technology, recipe, item and building.

Dataset facts this relies on (FactorioLab DSP 0.10.29.21950, vendored):

* A technology is an ``Item`` carrying a non-``None`` ``item.technology``
  (``lab/schema.py::Technology``).  306 of the 486 items are technologies.
* Every technology item has a same-id ``Recipe`` (306/306 checked).  That
  recipe's ``inputs`` ARE the research cost -- for 295 of them the inputs are
  matrix cubes; the remaining 11 are the pre-matrix starting technologies whose
  cost is raw components (circuit-board, magnetic-coil, gear, ...).
* ``item.technology.recipe_unlock`` lists the recipe ids the technology
  unlocks.  164 distinct recipes are named by some technology; every id named
  resolves to a real recipe (0 dangling).
* The 23 non-technology recipes named by NO technology are the DSP starting
  set: the 13 ``*-vein`` / ``ocean`` / ``crude-oil-seep`` extractions plus
  iron-ingot, copper-ingot, stone-brick, magnet, magnetic-coil, gear,
  circuit-board.  Those are tier 0.

Tier of a technology  = highest matrix colour among its research-cost inputs.
Tier of a recipe      = MIN tier over the technologies unlocking it (earliest
                        availability), 0 if no technology unlocks it.
Tier of an item       = MIN recipe tier over the recipes producing it.

MIN rather than MAX because the question is "when can I build this", and a
recipe reachable by two research paths is available at the earlier one.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from flab2bp.lab.data import load_vendored
from flab2bp.lab.schema import Dataset

#: Matrix cube -> tier.  ``df-dark-fog-matrix`` is not a cube colour on the
#: normal progression; it gets its own bucket (7) so it never contaminates the
#: white-cube tier and is easy to exclude.
MATRIX_TIER: dict[str, int] = {
    "electromagnetic-matrix": 1,  # blue
    "energy-matrix": 2,  # red
    "structure-matrix": 3,  # yellow
    "information-matrix": 4,  # purple
    "gravity-matrix": 5,  # green
    "universe-matrix": 6,  # white
    "df-dark-fog-matrix": 7,  # Dark Fog, off-ladder
}

TIER_NAME: dict[int, str] = {
    0: "start (no matrix)",
    1: "blue / electromagnetic",
    2: "red / energy",
    3: "yellow / structure",
    4: "purple / information",
    5: "green / gravity",
    6: "white / universe",
    7: "dark fog (off-ladder)",
}

#: Tiers the corpus sweeps.  7 is excluded: Dark Fog items have no normal DSP
#: catalog identity and ``rates.build_candidates`` refuses them outright.
LADDER_TIERS = (0, 1, 2, 3, 4, 5, 6)


class Tiers:
    """Every tier map, derived once."""

    def __init__(self, data: Dataset) -> None:
        self.data = data
        self.tech_items = tuple(item for item in data.items if item.technology is not None)
        self.tech_ids = frozenset(item.id for item in self.tech_items)

        self.tech: dict[str, int] = {}
        self.tech_cost: dict[str, list[str]] = {}
        for item in self.tech_items:
            assert item.technology is not None
            cost = sorted(data.recipe(item.id).inputs)
            self.tech_cost[item.id] = cost
            colours = [MATRIX_TIER[key] for key in cost if key in MATRIX_TIER]
            self.tech[item.id] = max(colours) if colours else 0

        # Recipe tier: earliest technology that unlocks it; 0 when nothing does
        # (starting recipes).  Technology research recipes themselves are given
        # their own technology's tier so they are excludable by tier too.
        self.recipe: dict[str, int] = {}
        for item in self.tech_items:
            assert item.technology is not None
            for recipe_id in item.technology.recipe_unlock:
                prior = self.recipe.get(recipe_id)
                self.recipe[recipe_id] = (
                    self.tech[item.id] if prior is None else min(prior, self.tech[item.id])
                )
        for recipe in data.recipes:
            if recipe.id in self.recipe:
                continue
            self.recipe[recipe.id] = self.tech[recipe.id] if recipe.id in self.tech_ids else 0

        # Item tier: earliest producing recipe.  Technology research recipes are
        # skipped -- they "produce" the technology item, which is not a thing
        # that flows on a belt.
        self.item: dict[str, int] = {}
        for recipe in data.recipes:
            if recipe.id in self.tech_ids:
                continue
            tier = self.recipe[recipe.id]
            for item_id in recipe.outputs:
                prior = self.item.get(item_id)
                self.item[item_id] = tier if prior is None else min(prior, tier)

        self.buildings: dict[str, int] = {
            item.id: self.item[item.id]
            for item in data.items
            if item.category in ("buildings", "buildings-alt") and item.id in self.item
        }
        self.unproducible_buildings = tuple(
            item.id
            for item in data.items
            if item.category in ("buildings", "buildings-alt") and item.id not in self.item
        )
        self.matrices: dict[str, int] = {
            matrix_id: self.item[matrix_id] for matrix_id in MATRIX_TIER if matrix_id in self.item
        }
        self.components: dict[str, int] = {
            item.id: self.item[item.id]
            for item in data.items
            if item.category == "components" and item.id in self.item
        }

    def to_json(self) -> dict[str, object]:
        def counts(mapping: dict[str, int]) -> dict[str, int]:
            return {str(k): v for k, v in sorted(collections.Counter(mapping.values()).items())}

        return {
            "dataset_version": dict(self.data.version),
            "matrix_tier": MATRIX_TIER,
            "tier_name": {str(k): v for k, v in TIER_NAME.items()},
            "technology": dict(sorted(self.tech.items())),
            "technology_research_cost": {k: v for k, v in sorted(self.tech_cost.items())},
            "recipe": dict(sorted(self.recipe.items())),
            "item": dict(sorted(self.item.items())),
            "building": dict(sorted(self.buildings.items())),
            "matrix": dict(sorted(self.matrices.items())),
            "component": dict(sorted(self.components.items())),
            "buildings_without_a_producing_recipe": list(self.unproducible_buildings),
            "counts": {
                "technology": counts(self.tech),
                "recipe": counts(self.recipe),
                "item": counts(self.item),
                "building": counts(self.buildings),
                "component": counts(self.components),
            },
        }


def main() -> int:
    data = load_vendored()
    tiers = Tiers(data)
    out = Path(__file__).parent / "tiers.json"
    out.write_text(json.dumps(tiers.to_json(), indent=1, sort_keys=False) + "\n")
    payload = tiers.to_json()
    counts = payload["counts"]
    assert isinstance(counts, dict)
    print(f"wrote {out}")
    for kind, table in counts.items():
        print(f"  {kind:<12} " + "  ".join(f"T{k}={v}" for k, v in table.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
