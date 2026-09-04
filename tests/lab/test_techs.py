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
    request = parse_url(
        "https://factoriolab.github.io/dsp/list?o=iron-ingot*60&ibe=conveyor-belt-2&v=11"
    )
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


# --- cargo stacking (multiple-belts design, section 5.2) --------------------

#: The four technologies that unlock the four sorter tiers, one each:
#: `basic-` -> sorter-1, `improved-` -> sorter-2, `high-efficiency-` ->
#: sorter-3, `integrated-` -> sorter-4 AND the Automatic Piler.  Listing all
#: four keeps the stack tuples four long, so a level's row can be read off
#: whole instead of against a truncated tier list.
_SORTER_TECHS = (
    "basic-logistics-system",
    "improved-logistics-system",
    "high-efficiency-logistics-system",
    "integrated-logistics-system",
)


def test_no_technology_set_means_everything_is_researched() -> None:
    data = load_vendored()
    request = parse_url(
        "https://factoriolab.github.io/dsp/list?o=iron-ingot*60&ibe=conveyor-belt-2&v=11"
    )
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.piler is True
    assert tiers.sorter_pick_stacks == (1, 1, 1, 4)  # level 6
    assert tiers.sorter_place_stacks == (1, 1, 1, 4)


def test_without_the_integrated_logistics_system_nothing_stacks() -> None:
    # The same tech unlocks the Pile Sorter and the Automatic Piler, so this
    # save has neither: every tier it can build picks and places 1.
    data = load_vendored()
    request = parse_url(
        _url_with_techs([t for t in _SORTER_TECHS if t != "integrated-logistics-system"])
    )
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.piler is False
    assert "sorter-4" not in tiers.sorter_item_ids
    assert set(tiers.sorter_pick_stacks) == {1}
    assert set(tiers.sorter_place_stacks) == {1}


def test_the_stack_tuples_are_as_long_as_the_tier_list() -> None:
    """Shorter than four on a save without the Pile Sorter, so nothing
    downstream may index them by a hard-coded tier number."""
    data = load_vendored()
    request = parse_url(_url_with_techs(["basic-logistics-system"]))
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.sorter_item_ids == ("sorter-1",)
    assert tiers.sorter_pick_stacks == (1,)
    assert tiers.sorter_place_stacks == (1,)


def test_the_level_is_the_highest_researched_pile_sorter_tech() -> None:
    researched = [*_SORTER_TECHS, "pile-sorter-1", "pile-sorter-2"]
    tiers = techs.logistics_tiers_for_request(
        parse_url(_url_with_techs(researched)), load_vendored()
    )
    assert tiers.sorter_pick_stacks == (1, 1, 1, 3)  # level 2
    assert tiers.sorter_place_stacks == (1, 1, 1, 2)


def test_a_gap_in_the_ladder_still_reads_the_highest_researched_level() -> None:
    """DSP's prerequisites make a gap impossible in a real save, but the URL
    is the player's to hand-edit; the highest researched level is the answer,
    not the longest unbroken prefix."""
    researched = [*_SORTER_TECHS, "pile-sorter-1", "pile-sorter-4"]
    tiers = techs.logistics_tiers_for_request(
        parse_url(_url_with_techs(researched)), load_vendored()
    )
    assert tiers.sorter_pick_stacks == (1, 1, 1, 4)  # level 4
    assert tiers.sorter_place_stacks == (1, 1, 1, 3)


def test_the_obsolete_cargo_stacking_ladder_is_ignored() -> None:
    """3301-3305 carry IsObsolete=1; researching them must move nothing."""
    researched = [*_SORTER_TECHS, *(f"sorter-cargo-stacking-{n}" for n in range(1, 6))]
    tiers = techs.logistics_tiers_for_request(
        parse_url(_url_with_techs(researched)), load_vendored()
    )
    assert tiers.sorter_pick_stacks == (1, 1, 1, 2)  # level 0, unmoved
    assert tiers.sorter_place_stacks == (1, 1, 1, 1)


def test_an_empty_technology_set_still_answers_with_a_stack_per_tier() -> None:
    """The `("sorter-1",)` fallback must not leave the tuples empty, or every
    downstream `max(...)` over them raises on an empty sequence."""
    data = load_vendored()
    request = replace(parse_url(_url_with_techs([])), researched_technology_ids=set())
    tiers = techs.logistics_tiers_for_request(request, data)
    assert tiers.sorter_item_ids == ("sorter-1",)
    assert tiers.sorter_pick_stacks == (1,)
    assert tiers.sorter_place_stacks == (1,)
    assert tiers.piler is False
