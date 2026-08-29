from __future__ import annotations

from dataclasses import replace

import pytest

from flab2bp.dsp import catalog
from flab2bp.lab import techs
from flab2bp.lab.data import load_vendored
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
