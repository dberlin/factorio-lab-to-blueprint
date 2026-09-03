from __future__ import annotations

from dataclasses import replace

import pytest

from flab2bp.dsp import catalog
from flab2bp.lab import params as P
from flab2bp.lab import techs
from flab2bp.lab.data import load_vendored, load_vendored_hash_index
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url


def _without_technologies(dataset: Dataset) -> Dataset:
    return replace(
        dataset,
        items=tuple(replace(item, technology=None) for item in dataset.items),
    )


def _expected(url: str, dataset: Dataset) -> catalog.BeltAltitudeRules:
    return catalog.belt_rules_for_technologies(
        parse_url(url).researched_technology_ids,
        {item.id for item in dataset.items if item.technology is not None},
    )


@pytest.mark.parametrize(
    ("url", "empty_first"),
    (
        ("https://factoriolab.github.io/dsp/list?o=iron-ingot*60001&v=11", False),
        ("https://factoriolab.github.io/dsp/list?o=iron-ingot*60002&v=11", True),
    ),
)
def test_same_url_explicit_datasets_never_share_rules(
    url: str,
    empty_first: bool,
) -> None:
    full = load_vendored()
    empty = _without_technologies(full)
    first, second = (empty, full) if empty_first else (full, empty)

    first_rules = techs.belt_rules_for_url(url, first)
    second_rules = techs.belt_rules_for_url(url, second)

    assert _expected(url, full) != _expected(url, empty)
    assert first_rules == _expected(url, first)
    assert second_rules == _expected(url, second)


def test_only_default_dataset_uses_the_bounded_cache() -> None:
    helper = techs._vendored_belt_rules_for_url
    helper.cache_clear()
    try:
        url = "https://factoriolab.github.io/dsp/list?o=iron-ingot*61000&v=11"
        first = techs.belt_rules_for_url(url)
        second = techs.belt_rules_for_url(url)
        assert second is first
        assert helper.cache_info().hits == 1

        before_explicit = helper.cache_info()
        explicit = _without_technologies(load_vendored())
        assert techs.belt_rules_for_url(url, explicit) == _expected(url, explicit)
        assert helper.cache_info() == before_explicit

        for amount in range(1, 514):
            techs.belt_rules_for_url(
                f"https://factoriolab.github.io/dsp/list?o=copper-ingot*{amount}&v=11"
            )
        info = helper.cache_info()
        assert info.maxsize == 512
        assert info.currsize == 512
    finally:
        helper.cache_clear()


def _url_with_techs(tech_ids: list[str], belt: str = "conveyor-belt-2") -> str:
    techs_table = load_vendored_hash_index().technologies
    tre = P.ZFIELDSEP.join(P.n_to_id(techs_table.index(t)) for t in tech_ids)
    return f"https://factoriolab.github.io/dsp/list?o=iron-ingot*60&ibe={belt}&tre={tre}&v=11"


def test_no_technology_set_unlocks_every_belt_and_sorter_above_the_floor() -> None:
    data = load_vendored()
    request = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*60&ibe=conveyor-belt-2&v=11")
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-2", "conveyor-belt-3")
    assert tiers.sorter_item_ids == ("sorter-1", "sorter-2", "sorter-3", "sorter-4")
    assert tiers.from_url is False


def test_belt_one_floor_lists_every_belt() -> None:
    data = load_vendored()
    request = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*60&v=11")
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-1", "conveyor-belt-2", "conveyor-belt-3")


def test_without_planetary_logistics_there_is_no_belt_three() -> None:
    data = load_vendored()
    request = parse_url(
        _url_with_techs(
            [
                "basic-logistics-system",
                "improved-logistics-system",
                "high-efficiency-logistics-system",
            ]
        )
    )
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-2",)
    assert tiers.sorter_item_ids == ("sorter-1", "sorter-2", "sorter-3")
    assert tiers.from_url is True


def test_without_integrated_logistics_there_is_no_pile_sorter() -> None:
    data = load_vendored()
    request = parse_url(
        _url_with_techs(
            [
                "basic-logistics-system",
                "improved-logistics-system",
                "high-efficiency-logistics-system",
                "planetary-logistics-system",
            ]
        )
    )
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-2", "conveyor-belt-3")
    assert "sorter-4" not in tiers.sorter_item_ids


def test_the_floor_is_present_even_when_unresearched() -> None:
    """FactorioLab's belt choice is authoritative, researched or not."""
    data = load_vendored()
    request = parse_url(_url_with_techs(["basic-logistics-system"], belt="conveyor-belt-3"))
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-3",)


def test_a_belt_at_the_floors_exact_speed_is_not_listed_as_an_upgrade() -> None:
    """``>`` not ``>=``: a second belt at the floor's own speed must never be
    admitted as an upgrade.  If it were, `_to_build_spec` would list it in
    `belt_upgrades` right next to the floor and `BuildSpec._tiers_are_ordered`
    would reject the spec, since two tiers of equal speed are not "strictly
    faster than the one before"."""
    data = load_vendored()
    floor_item = next(item for item in data.items if item.id == "conveyor-belt-1")
    twin = replace(floor_item, id="conveyor-belt-1-twin", name="Conveyor Belt Twin")
    items = tuple(
        replace(
            item,
            technology=replace(
                item.technology, recipe_unlock=(*item.technology.recipe_unlock, twin.id)
            ),
        )
        if item.id == "basic-logistics-system" and item.technology is not None
        else item
        for item in data.items
    )
    data = replace(data, items=(*items, twin))
    request = parse_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*60&v=11")
    tiers = techs.logistics_tiers_for_request(request, data)
    assert twin.id not in tiers.belt_item_ids


def test_an_empty_technology_set_falls_back_to_sorter_one() -> None:
    data = load_vendored()
    # `_url_with_techs([])` produces a `tre=` that decodes to `None` (no
    # technology set at all, meaning everything researched) rather than an
    # explicit empty set, so build the empty-set request directly.
    request = replace(parse_url(_url_with_techs([])), researched_technology_ids=set())
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.belt_item_ids == ("conveyor-belt-2",)
    assert tiers.sorter_item_ids == ("sorter-1",)
