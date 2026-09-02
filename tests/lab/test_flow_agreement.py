"""The derived solve agrees with FactorioLab's own flow, capture by capture.

Every CSV under ``tests/fixtures/flows`` is a FactorioLab flow export captured
from factoriolab.github.io for the URL on its first line.  Nothing here is
pinned: each request is solved from the URL alone, and the result must run the
same crafting recipes FactorioLab ran and belt in only items FactorioLab also
lists as inputs, including everything FactorioLab took from an extraction
recipe (vein, pump, seep or orbital collector).

This is the durable form of the evidence behind pricing extraction the way
FactorioLab's ``adjustCosts`` does (``solve._extraction_producers``): the
deuteron-fuel-rod URL that reported hydrogen crafted through
``graphene-advanced`` from fire ice, the graphene URL that crafted sulfuric
acid from stone and water, the space-warper URL where ``graphene-advanced`` on
collected fire ice is nonetheless the right route, and the plain
deuteron-fuel-rod URL where FactorioLab crafts deuterium from collected
hydrogen rather than collecting deuterium.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import parse_flow_csv
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.solve import solve

FLOWS = Path(__file__).parent.parent / "fixtures" / "flows"

#: FactorioLab crafts proliferator inside the flow; this project belts it in
#: from outside by design (spec section 4), so those rows are not a divergence.
BELTED_BY_DESIGN = frozenset({"proliferator-1", "proliferator-2", "proliferator-3"})

#: ``universe-matrix.csv`` is deliberately absent: its MILP takes tens of
#: seconds and the bench covers it.
CAPTURES = (
    "deuteron-fuel-rod-collectors",
    "deuteron-fuel-rod",
    "strange-matter",
    "graphene",
    "plastic",
    "energy-matrix",
    "casimir-crystal",
    "information-matrix",
    "space-warper",
    "space-warper-no-advanced",
)


@pytest.fixture(scope="module")
def data() -> Dataset:
    return load_vendored()


@pytest.mark.parametrize("name", CAPTURES)
def test_derived_solve_agrees_with_factoriolabs_flow(name: str, data: Dataset) -> None:
    flow = parse_flow_csv((FLOWS / f"{name}.csv").read_text())
    plan = solve(data, parse_url(flow.source_url))

    crafted_by_factoriolab: set[str] = set()
    extracted_by_factoriolab: set[str] = set()
    for row in flow.rows:
        recipe = data.get_recipe(row.recipe_id) if row.recipe_id else None
        if recipe is None:
            continue
        if recipe.is_mining:
            if row.item_id:
                extracted_by_factoriolab.add(row.item_id)
        elif recipe.id not in BELTED_BY_DESIGN:
            crafted_by_factoriolab.add(recipe.id)

    assert {g.recipe_id for g in plan.groups} == crafted_by_factoriolab
    assert set(plan.external_inputs) <= set(flow.external_items(data))
    assert extracted_by_factoriolab <= set(plan.external_inputs)
