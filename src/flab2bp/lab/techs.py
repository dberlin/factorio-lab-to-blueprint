"""What a FactorioLab URL's researched technologies allow a belt to do.

One function, and it exists because the answer was being derived in four
places and reached only one of them.

``pipeline`` derived the rules and passed them to freeform and to the
validator.  ``scripts/audit.py`` derived nothing, so every corpus cell was both
BUILT and JUDGED against whatever the defaults happened to be rather than
against the save the URL describes -- a measurement that could not have caught a
technology-dependent defect in either direction, while reading exactly like one
that could.  ``scripts/ab_compare.py``, ``scripts/solve_probe.py`` and
``flab2bp.bench.runner`` had the same hole.

So the derivation lives here and every caller asks the same question of the same
code.  It sits in ``lab`` rather than in ``dsp`` because it needs the URL parser
and the dataset; ``lab`` already depends on ``dsp`` and ``dsp`` depends on
nothing in ``lab``, so the direction is the one that was already there.
"""

from __future__ import annotations

from functools import lru_cache

from flab2bp.dsp import catalog
from flab2bp.lab.data import load_vendored
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url

__all__ = ["belt_rules_for_url"]

def _belt_rules(url: str, dataset: Dataset) -> catalog.BeltAltitudeRules:
    return catalog.belt_rules_for_technologies(
        parse_url(url).researched_technology_ids,
        {item.id for item in dataset.items if item.technology is not None},
    )


@lru_cache(maxsize=512)
def _vendored_belt_rules_for_url(url: str) -> catalog.BeltAltitudeRules:
    return _belt_rules(url, load_vendored())


def belt_rules_for_url(
    url: str, dataset: Dataset | None = None
) -> catalog.BeltAltitudeRules:
    """The belt altitude rules this URL's save implies.

    How high a belt may go, and whether it may climb with no horizontal run at
    all, are properties of the player's researched technologies.  FactorioLab
    already recorded that set in the URL, and this project's standing rule is
    that FactorioLab's answer is authoritative -- so this is never a flag and
    never a default we chose.

    A URL carrying no technology set at all is **not** a save with nothing
    researched: FactorioLab reads absence as every technology researched, which
    :func:`catalog.belt_rules_for_technologies` documents against
    ``settings-store.ts::computeSettings``.  Passing ``None`` straight through
    is what preserves that.
    """
    if dataset is None:
        return _vendored_belt_rules_for_url(url)
    return _belt_rules(url, dataset)
