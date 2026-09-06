"""Fixtures shared by the layout suites.

The mall URL below is the one whose hierarchical decomposition produced blocks
the placers refused; cutting one recipe out of its ``all-products`` candidate is
the smallest spec that reproduces those refusals, so both placer suites build
their block from the same helper rather than from two drifting copies.
"""

from __future__ import annotations

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.lab.url import parse_url
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, _build_candidates_canonical
from flab2bp.spec import BuildSpec

MALL_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJwlx7uOwjAUhOG3OcUUKAYWhWKaY4mgVRaBEBAogRQWayVyuKTys6PEzf"
    ".NNNzAZHkmDdcnzBbD0ArTXBp-YH6kod0PtyZ-hxQSqHsgk8Bd4pLQG2Ak0Fbp223yL1Em1sfkMpEPeFoY8TyPdWPLsd3YFkZc"
    "3VMn4q41rbjuybmEuucWJ5xxxwMv9FhAN9ADtILeoI-o.9Ap7CraQrwP7GIbXSzFtx0LedOYL5cQRDE_&v=11"
)


def one_recipe_spec(spec: BuildSpec, recipe: str, count: int) -> BuildSpec:
    """``count`` machines of ``recipe`` cut out of ``spec`` as a self-contained spec."""
    group = next(g for g in spec.groups if g.recipe_id == recipe)
    group = group.model_copy(update={"count": count})
    inputs = {item: rate * count for item, rate in group.inputs_per_machine.items()}
    outputs = {item: rate * count for item, rate in group.outputs_per_machine.items()}
    spray = {i: True for i in spec.spray_lanes if i in inputs} if group.is_proliferated else {}
    if spray:
        for item, rate in spec.external_inputs.items():
            if item.startswith("proliferator"):
                inputs[item] = rate / spec.machine_count * count
    data = spec.model_dump()
    data.update(
        {
            "groups": (group,),
            "external_inputs": inputs,
            "outputs": outputs,
            "surplus_outputs": {},
            "spray_lanes": spray,
            "lanes_requiring_split": frozenset(),
            "belt_required_edges": frozenset(),
            "coproduct_buffer_proofs": (),
            "label": f"one-recipe-{recipe}-{count}",
        }
    )
    return BuildSpec(**data)


@pytest.fixture(scope="session")
def mall_all_products() -> tuple[BuildSpec, bool]:
    data = canonicalize_dataset(load_vendored())
    request = canonicalize_request(parse_url(MALL_URL))
    rules = belt_rules_for_url(MALL_URL, data)
    spec_set = _build_candidates_canonical(
        data, request, tier=None, candidate_policies=DEFAULT_CANDIDATE_POLICIES, flow=None
    )
    spec = next(c for c in spec_set.candidates if c.label == "all-products")
    return spec, rules.vertical_construction
