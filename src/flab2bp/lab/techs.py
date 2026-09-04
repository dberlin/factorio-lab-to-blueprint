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

from fractions import Fraction
from functools import lru_cache

from flab2bp.dsp import catalog
from flab2bp.lab.data import load_vendored
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import LabRequest, parse_url

__all__ = ["belt_rules_for_url", "logistics_tiers_for_request"]


def _belt_rules(url: str, dataset: Dataset) -> catalog.BeltAltitudeRules:
    return catalog.belt_rules_for_technologies(
        parse_url(url).researched_technology_ids,
        {item.id for item in dataset.items if item.technology is not None},
    )


@lru_cache(maxsize=512)
def _vendored_belt_rules_for_url(url: str) -> catalog.BeltAltitudeRules:
    return _belt_rules(url, load_vendored())


def belt_rules_for_url(url: str, dataset: Dataset | None = None) -> catalog.BeltAltitudeRules:
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


def logistics_tiers_for_request(request: LabRequest, dataset: Dataset) -> catalog.LogisticsTiers:
    """The belts and sorters this request's save can build.

    Data-driven: a belt or sorter is buildable when some researched
    technology item lists it in ``recipe_unlock``.  ``None`` for the
    researched set means every technology, as :func:`belt_rules_for_url`
    documents.  The request's own belt is always included, researched or not,
    because FactorioLab chose it and FactorioLab's choice is authoritative.

    A save whose explicit technology set unlocks no sorter at all gets
    ``("sorter-1",)``: it cannot build belts either, and refusing every build
    over it would help nobody.
    """
    technology_items = [item for item in dataset.items if item.technology is not None]
    researched = request.researched_technology_ids
    unlocked: set[str] = set()
    for item in technology_items:
        assert item.technology is not None
        if researched is None or item.id in researched:
            unlocked.update(item.technology.recipe_unlock)

    floor_id = request.belt_id or "conveyor-belt-1"
    floor_speed = dataset.belt_speed(floor_id)
    belts = {
        item.id
        for item in dataset.items
        if item.belt is not None
        and item.id in unlocked
        # Strictly faster than the floor: a belt at the SAME speed is not an
        # "upgrade".  `_to_build_spec` would list it in `belt_upgrades`
        # anyway, and `BuildSpec._tiers_are_ordered` requires each upgrade to
        # be strictly faster than the one before, so admitting a same-speed
        # belt here would crash there instead of harmlessly deduplicating.
        and item.belt.speed > floor_speed
    }
    belts.add(floor_id)
    belt_item_ids = tuple(sorted(belts, key=lambda item_id: (dataset.belt_speed(item_id), item_id)))

    sorter_rates: dict[str, Fraction] = {}
    for item in dataset.items:
        numeric = catalog.get_item_id(item.id)
        if numeric in catalog.SORTER_RATE_AT_1 and item.id in unlocked:
            sorter_rates[item.id] = catalog.SORTER_RATE_AT_1[numeric]
    sorter_item_ids = tuple(
        sorted(sorter_rates, key=lambda item_id: (sorter_rates[item_id], item_id))
    )
    if not sorter_item_ids:
        sorter_item_ids = ("sorter-1",)

    # DSP 0.10.34 has two cargo-stacking research ladders and only ONE is
    # reachable.  `sorter-cargo-stacking-{n}` (game techs 3301-3305) carries
    # IsObsolete = 1, which is what hides a tech from the tree
    # (`UITechNode.cs:914`), so it cannot be researched and moves nothing; the
    # live ladder is `pile-sorter-{n}` (game techs 3311-3316).  Reading the
    # obsolete ids here would grant stacks the game never grants.  See
    # `dsp/data/stacking.json`'s `obsolete_ladder`.
    #
    # Both ladders are `category: upgrades` with no `recipeUnlock`, so a level
    # is tested by id membership in `researched` rather than through
    # `unlocked`.  `integrated-logistics-system` is the sole `recipeUnlock` for
    # both `automatic-piler` and `sorter-4`, which is why a save without it has
    # no stacking at all: no Pile Sorter to stack with, and no piler either.
    level = (
        catalog.SORTER_STACKING_LEVELS
        if researched is None
        else max(
            (
                n
                for n in range(1, catalog.SORTER_STACKING_LEVELS + 1)
                if f"pile-sorter-{n}" in researched
            ),
            default=0,
        )
    )

    return catalog.LogisticsTiers(
        belt_item_ids=belt_item_ids,
        sorter_item_ids=sorter_item_ids,
        from_url=researched is not None,
        piler="automatic-piler" in unlocked,
        # `catalog.item_id` is the non-optional resolver, and `sorter_item_ids`
        # is always a subset of the sorters the catalog knows, so it cannot
        # raise here.  The tuples are as long as `sorter_item_ids`.
        sorter_pick_stacks=tuple(
            catalog.sorter_pick_stack(catalog.item_id(s), level) for s in sorter_item_ids
        ),
        sorter_place_stacks=tuple(
            catalog.sorter_place_stack(catalog.item_id(s), level) for s in sorter_item_ids
        ),
    )
