"""Canonical Dark Fog aliases and provenance-gated DF-only source items."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import FlowError, flow_from_text, load_flow, pin_request
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.candidates import build_candidates

DARK_FOG_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNyr0KwkAQBOC3uWJAuIuJqbbZYLQQMaKRa"
    "9UUMR7BBEWbe3bJ712z-80wNaUhIlETlwhETdtL.3g3lPGQbggjCajOP-cYkRyZI5jNDCWnc"
    "PLMC6xma-em24x17tw6Lr3Fw7Py.JpcEFJhSEMKQ9zfNaQorwWxaIovHaBxR4U3eA8-gyvLT"
    "3CLZIMks8lRGNOQtmzXNhMfUuoPq0xHzg__&v=11"
)
DARK_FOG_FLOW = Path(__file__).parents[1] / "fixtures" / "flow_dark_fog_exact.csv"
LOGISTICS_URL = "https://factoriolab.github.io/dsp/list?o=logistics-bot*60&v=11"


def _df_only_flow(*, include_source: bool) -> str:
    rows = [
        f'"{LOGISTICS_URL}"',
        "Item,Items,Recipe,Machines,Machine,Modules",
        'logistics-bot,=60,logistics-bot,=2,assembling-machine-2,"1 "',
        "iron-ingot,=120,,,,",
        "processor,=60,,,,",
    ]
    if include_source:
        rows.append("df-only-resource,=60,,,,")
    return "\r\n".join(rows) + "\r\n"


def _with_df_only_logistics_input(data: Dataset) -> Dataset:
    original = data.recipe("logistics-bot")
    changed = replace(
        original,
        inputs=MappingProxyType(
            {
                "df-only-resource": Fraction(1),
                "iron-ingot": Fraction(2),
                "processor": Fraction(1),
            }
        ),
    )
    return replace(
        data,
        recipes=tuple(changed if recipe.id == original.id else recipe for recipe in data.recipes),
    )


@pytest.fixture(scope="module")
def data() -> Dataset:
    return load_vendored()


def test_alias_only_url_uses_catalog_recipe_ids(data: Dataset) -> None:
    (spec,) = build_candidates(data, parse_url(DARK_FOG_URL), count=1).candidates

    assert "combustible-unit" in {group.recipe_id for group in spec.groups}
    assert "supersonic-missile-set" in spec.outputs
    assert not any(group.recipe_id.startswith("df-") for group in spec.groups)
    assert not any(item.startswith("df-") for item in spec.outputs)


def test_canonical_and_alias_objectives_merge_into_one_demand(data: Dataset) -> None:
    url = (
        "https://factoriolab.github.io/dsp/list?"
        "o=df-combustible-unit*30&o=combustible-unit*30&v=11"
    )
    (spec,) = build_candidates(data, parse_url(url), count=1).candidates

    assert spec.outputs == {"combustible-unit": Fraction(1)}
    assert [g.recipe_id for g in spec.groups] == ["combustible-unit"]


def test_captured_flow_aliases_share_canonical_identity_and_provenance() -> None:
    flow = load_flow(DARK_FOG_FLOW, url=DARK_FOG_URL)

    assert flow.source_url == DARK_FOG_URL
    assert "df-combustible-unit" not in flow.by_item
    assert "combustible-unit" in flow.by_item
    assert "df-combustible-unit" not in flow.chosen_recipe_ids
    assert "combustible-unit" in flow.chosen_recipe_ids


def test_flow_from_text_canonicalizes_observed_spelling_aliases() -> None:
    url = "https://factoriolab.github.io/dsp/list?o=combustible-unit*1&v=11"
    flow = flow_from_text(
        "\r\n".join(
            [
                f'"{url}"',
                "Item,Items,Recipe,Machines,Machine,Modules",
                'df-combustion-unit,=1,df-combustion-unit,=1,assembling-machine-2,"1 "',
            ]
        )
        + "\r\n",
        url=url,
    )

    assert set(flow.by_item) == {"combustible-unit"}
    assert flow.chosen_recipe_ids == {"combustible-unit"}
    assert flow.source_url == url


def test_captured_alias_and_canonical_rows_produce_the_same_selection() -> None:
    url = "https://factoriolab.github.io/dsp/list?o=combustible-unit*1&v=11"

    def captured(item_id: str) -> str:
        return (
            "\r\n".join(
                [
                    f'"{url}"',
                    "Item,Items,Recipe,Machines,Machine,Modules",
                    f'{item_id},=1,{item_id},=1,assembling-machine-2,"1 "',
                ]
            )
            + "\r\n"
        )

    alias = flow_from_text(captured("df-combustible-unit"), url=url)
    canonical = flow_from_text(captured("combustible-unit"), url=url)

    assert alias == canonical
    assert alias.source_url == url



def test_alias_and_canonical_flow_rows_merge_rates() -> None:
    url = "https://factoriolab.github.io/dsp/list?o=combustible-unit*2&v=11"
    flow = flow_from_text(
        "\r\n".join(
            [
                f'"{url}"',
                "Item,Items,Recipe,Machines,Machine,Modules",
                'df-combustible-unit,=1,df-combustible-unit,=1,assembling-machine-2,"1 "',
                'combustible-unit,=1,combustible-unit,=1,assembling-machine-2,"1 "',
            ]
        )
        + "\r\n",
        url=url,
    )

    assert len(flow.rows) == 1
    assert flow.rows[0].item_id == "combustible-unit"
    assert flow.rows[0].recipe_id == "combustible-unit"
    assert flow.rows[0].items == 2
    assert flow.rows[0].machines == 2


def test_df_only_output_is_refused_even_when_the_flow_lists_it(data: Dataset) -> None:
    url = "https://factoriolab.github.io/dsp/list?o=df-only-resource*1&v=11"
    source = data.recipe("logistics-bot")
    synthetic = replace(
        source,
        id="df-only-resource",
        inputs=MappingProxyType({"iron-ingot": Fraction(1)}),
        outputs=MappingProxyType({"df-only-resource": Fraction(1)}),
    )
    custom = replace(data, recipes=(*data.recipes, synthetic))
    flow = flow_from_text(
        "\r\n".join(
            [
                f'"{url}"',
                "Item,Items,Recipe,Machines,Machine,Modules",
                'df-only-resource,=1,df-only-resource,=1,assembling-machine-2,"1 "',
                "iron-ingot,=1,,,,",
            ]
        )
        + "\r\n",
        url=url,
    )

    with pytest.raises(FlowError, match="df-only-resource.*cannot be a blueprint output"):
        _ = pin_request(parse_url(url), custom, flow)


def test_df_only_non_demand_row_does_not_authorize_an_input(data: Dataset) -> None:
    custom = _with_df_only_logistics_input(data)
    text = _df_only_flow(include_source=True).replace(
        "df-only-resource,=60", "df-only-resource,=0"
    )
    flow = flow_from_text(text, url=LOGISTICS_URL)
    request = pin_request(parse_url(LOGISTICS_URL), custom, flow)

    with pytest.raises(FlowError, match="df-only-resource.*external input"):
        _ = build_candidates(custom, request, count=1, flow=flow)

def test_df_only_internal_product_is_refused(data: Dataset) -> None:
    logistics = replace(
        data.recipe("logistics-bot"),
        inputs=MappingProxyType(
            {
                "df-only-resource": Fraction(1),
                "iron-ingot": Fraction(2),
                "processor": Fraction(1),
            }
        ),
    )
    producer = replace(
        data.recipe("gear"),
        outputs=MappingProxyType({"df-only-resource": Fraction(1)}),
    )
    custom = replace(
        data,
        recipes=tuple(
            logistics
            if recipe.id == logistics.id
            else producer
            if recipe.id == producer.id
            else recipe
            for recipe in data.recipes
        ),
    )
    flow = flow_from_text(
        "\r\n".join(
            [
                f'"{LOGISTICS_URL}"',
                "Item,Items,Recipe,Machines,Machine,Modules",
                'logistics-bot,=60,logistics-bot,=2,assembling-machine-2,"1 "',
                'df-only-resource,=60,gear,=1,assembling-machine-2,"1 "',
                "iron-ingot,=180,,,,",
                "processor,=60,,,,",
            ]
        )
        + "\r\n",
        url=LOGISTICS_URL,
    )
    request = pin_request(parse_url(LOGISTICS_URL), custom, flow)

    with pytest.raises(FlowError, match="df-only-resource.*internal product"):
        _ = build_candidates(custom, request, count=1, flow=flow)


def test_df_only_explicit_input_is_an_external_source(data: Dataset) -> None:
    custom = _with_df_only_logistics_input(data)
    flow = flow_from_text(_df_only_flow(include_source=True), url=LOGISTICS_URL)
    request = pin_request(parse_url(LOGISTICS_URL), custom, flow)
    (spec,) = build_candidates(custom, request, count=1, flow=flow).candidates

    assert [group.recipe_id for group in spec.groups] == ["logistics-bot"]
    assert "df-only-resource" in spec.external_inputs


def test_df_only_derived_objective_is_refused(data: Dataset) -> None:
    url = "https://factoriolab.github.io/dsp/list?o=df-only-resource*1&v=11"

    with pytest.raises(KeyError, match="df-only-resource.*Dark Fog"):
        _ = build_candidates(data, parse_url(url), count=1)


def test_df_only_implicit_input_is_refused(data: Dataset) -> None:
    custom = _with_df_only_logistics_input(data)
    flow = flow_from_text(_df_only_flow(include_source=False), url=LOGISTICS_URL)
    request = pin_request(parse_url(LOGISTICS_URL), custom, flow)

    with pytest.raises(FlowError, match="df-only-resource.*positive demand"):
        _ = build_candidates(custom, request, count=1, flow=flow)


def test_unrelated_item_identity_is_unchanged(data: Dataset) -> None:
    url = "https://factoriolab.github.io/dsp/list?o=graphene*60&v=11"
    (spec,) = build_candidates(data, parse_url(url), count=1).candidates

    assert spec.outputs == {"graphene": Fraction(1)}
    assert "graphene" in {group.recipe_id for group in spec.groups}
