"""Pinning the proliferation frontier to what FactorioLab's flow actually sprays.

A proliferator tier is an **implied input**: the sprayed item is belted in from
outside, so choosing a tier changes what the block consumes.  The rule is that
the inputs FactorioLab chose may never be changed, implied ones included -- so
when a flow is supplied, the frontier is not a frontier any more.

``proliferator_from_request`` reasons that an absent proliferator in a URL "is
not a constraint", and that is right *for a URL*, which states what is available
rather than what is used.  A solved flow states what is used.  The difference is
not academic: measured against a real export whose ``Modules`` column is empty,
an unpinned products policy asks the player to belt in ``proliferator-3``.
``test_unpinned_frontier_would_add_a_proliferator_input`` pins that, so none of
the assertions below can pass vacuously.

A separate file from ``test_candidates.py`` deliberately: another agent is live
on the unpinned frontier, and new tests in a new file do not collide.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import (
    FlowError,
    FlowSelection,
    parse_flow_csv,
    pin_request,
    unsupplied_inputs,
)
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.adjust import ProliferatorTier
from flab2bp.rates.candidates import build_candidates, proliferation_from_flow
from flab2bp.spec import ProliferatorMode

URL = (
    "https://factoriolab.github.io/dsp/list?o=graphene*60&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
)

_HEADER = "Item,Items,Recipe,Machines,Machine,Modules"

#: The real captured flow's selection: graphene from energetic graphite, with
#: coal and sulfuric acid belted in. `Modules` is `"1 "` -- a count and an EMPTY
#: module id -- which is what a real export writes for an unfilled slot.
_UNSPRAYED = (
    'graphene,=60,graphene,=3/2,chemical-plant,"1 "',
    'energetic-graphite,=90,energetic-graphite,=3,arc-smelter,"1 "',
    "coal,=180,coal-vein,=6,mining-machine,",
    "sulfuric-acid,=30,sulphuric-acid-vein,=3/5,mining-machine,",
)


def _flow(*rows: str, header: str = _HEADER) -> FlowSelection:
    return parse_flow_csv("\r\n".join([f'"{URL}"', header, *rows]) + "\r\n")


def _sprayed(module: str) -> FlowSelection:
    """The exporter writes `Modules` pre-quoted, which is what makes a cell
    containing commas legal CSV. Reproduced here rather than approximated."""
    rows = list(_UNSPRAYED)
    rows[0] = f'graphene,=60,graphene,=3/2,chemical-plant,"1 {module}"'
    return _flow(*rows)


@pytest.fixture(scope="module")
def data() -> Dataset:
    return load_vendored()


class TestReadingWhatTheFlowSprays:
    def test_an_empty_module_slot_is_not_proliferation(self) -> None:
        """`"1 "` is a count with no module. It must not read as sprayed."""
        assert _flow(*_UNSPRAYED).proliferator_modules() == {}
        assert proliferation_from_flow(_flow(*_UNSPRAYED)) == (
            ProliferatorTier.NONE,
            (),
            frozenset(),
        )

    def test_a_sprayed_recipe_is_read_with_its_tier_and_mode(self) -> None:
        flow = _sprayed("proliferator-2-speed")
        assert flow.proliferator_modules() == {"graphene": "proliferator-2-speed"}
        assert proliferation_from_flow(flow) == (
            ProliferatorTier.MK2,
            (ProliferatorMode.SPEED,),
            frozenset({"graphene"}),
        )

    def test_a_module_id_with_no_count_still_reads(self) -> None:
        """Keyed off the token naming a proliferator, not off position."""
        rows = list(_UNSPRAYED)
        rows[0] = 'graphene,=60,graphene,=3/2,chemical-plant,"proliferator-1-products"'
        assert _flow(*rows).proliferator_modules() == {"graphene": "proliferator-1-products"}

    def test_two_different_proliferators_on_one_recipe_refuses(self) -> None:
        flow_text = _sprayed("proliferator-2-speed,1 proliferator-3-speed")
        with pytest.raises(FlowError, match="more than one proliferator module"):
            flow_text.proliferator_modules()

    def test_mixed_tiers_across_recipes_refuse(self) -> None:
        """One tier per build, so a mixed flow cannot be honoured exactly."""
        rows = list(_UNSPRAYED)
        rows[0] = 'graphene,=60,graphene,=3/2,chemical-plant,"1 proliferator-1-speed"'
        rows[1] = (
            'energetic-graphite,=90,energetic-graphite,=3,arc-smelter,"1 proliferator-3-speed"'
        )
        with pytest.raises(FlowError, match="more than one proliferator tier"):
            proliferation_from_flow(_flow(*rows))

    def test_an_unknown_module_refuses(self) -> None:
        with pytest.raises(FlowError, match="not a\n?\\s*proliferator module"):
            proliferation_from_flow(_sprayed("proliferator-9-warp"))


class TestPinnedFrontier:
    def test_unpinned_frontier_would_add_a_proliferator_input(self, data: Dataset) -> None:
        """The instrument check, and the defect this change removes.

        Without a flow the frontier explores proliferation and the winning
        candidate belts in a proliferator the player never named. If this ever
        stops holding, every assertion below is vacuous.
        """
        unpinned = build_candidates(data, parse_url(URL), count=3)
        assert len(unpinned.candidates) == 3
        assert any(
            any(i.startswith("proliferator") for i in spec.external_inputs)
            for spec in unpinned.candidates
        )

    def test_an_unsprayed_flow_yields_one_unproliferated_build(self, data: Dataset) -> None:
        """No frontier: the choice is made, so there is nothing to explore."""
        flow = _flow(*_UNSPRAYED)
        pinned = build_candidates(data, pin_request(parse_url(URL), data, flow), flow=flow)
        (spec,) = pinned.candidates
        assert spec.label == "flow-pinned"
        assert not spec.is_proliferated
        assert dict(spec.external_inputs) == {
            "coal": Fraction(3),
            "sulfuric-acid": Fraction(1, 2),
        }
        assert unsupplied_inputs(flow, data, spec.external_inputs) == ()

    def test_the_pin_follows_the_flow_rather_than_forbidding_spray(self, data: Dataset) -> None:
        """A flow that DOES spray gets built sprayed, at its own tier.

        The rule is "do not change what FactorioLab chose", not "never
        proliferate". Speed mode, because it is legal for every recipe, so this
        tests the pin rather than the productivity whitelist.
        """
        flow = _sprayed("proliferator-2-speed")
        pinned = build_candidates(data, pin_request(parse_url(URL), data, flow), flow=flow)
        (spec,) = pinned.candidates
        assert spec.label == "flow-pinned-mk2"
        assert spec.is_proliferated
        assert "proliferator-2" in spec.external_inputs
        # ONLY the recipes the flow sprays, in each recipe's authored mode.
        # Spraying a recipe FactorioLab left alone changes its input rates, so
        # the per-recipe fixed-mode map is part of the observable pin.
        assert {g.recipe_id for g in spec.groups if g.is_proliferated} == {"graphene"}
        assert {group.proliferator_mode for group in spec.groups if group.is_proliferated} == {
            ProliferatorMode.SPEED
        }
        # And the belted proliferator is legal precisely because the flow sprays.
        assert flow.uses_proliferator
        assert (
            unsupplied_inputs(
                flow,
                data,
                spec.external_inputs,
                exempt=frozenset(i for i in spec.external_inputs if i.startswith("proliferator")),
            )
            == ()
        )

    @pytest.mark.parametrize(
        ("flow_module", "selected_tier", "expected_item", "expected_label"),
        [
            (
                "proliferator-2-speed",
                ProliferatorTier.MK3,
                "proliferator-3",
                "flow-pinned-mk3",
            ),
            (
                "proliferator-3-speed",
                ProliferatorTier.MK2,
                "proliferator-2",
                "flow-pinned-mk2",
            ),
        ],
    )
    def test_an_explicit_tier_overrides_the_flow_tier(
        self,
        data: Dataset,
        flow_module: str,
        selected_tier: ProliferatorTier,
        expected_item: str,
        expected_label: str,
    ) -> None:
        flow = _sprayed(flow_module)
        pinned = build_candidates(
            data,
            pin_request(parse_url(URL), data, flow),
            tier=selected_tier,
            flow=flow,
        )
        (spec,) = pinned.candidates

        assert spec.label == expected_label
        sprayed_inputs = {
            item_id: rate
            for item_id, rate in spec.external_inputs.items()
            if item_id.startswith("proliferator-")
        }
        assert set(sprayed_inputs) == {expected_item}

        (sprayed_group,) = (group for group in spec.groups if group.is_proliferated)
        sprays = data.module(f"{expected_item}-speed").sprays
        assert sprays is not None
        sprayed_item_rate = (
            sum(sprayed_group.inputs_per_machine.values(), Fraction()) * sprayed_group.count
        )
        assert sprayed_inputs[expected_item] == sprayed_item_rate / sprays

    def test_explicit_none_clears_the_flow_spray_modes(self, data: Dataset) -> None:
        flow = _sprayed("proliferator-3-speed")
        pinned = build_candidates(
            data,
            pin_request(parse_url(URL), data, flow),
            tier=ProliferatorTier.NONE,
            flow=flow,
        )
        (spec,) = pinned.candidates

        assert spec.label == "flow-pinned"
        assert not spec.is_proliferated
        assert all(not item_id.startswith("proliferator-") for item_id in spec.external_inputs)
        assert all(group.proliferator_mode is ProliferatorMode.NONE for group in spec.groups)

    def test_explicit_none_ignores_an_unknown_flow_proliferator(self, data: Dataset) -> None:
        flow = _sprayed("proliferator-9-warp")
        pinned = build_candidates(
            data,
            pin_request(parse_url(URL), data, flow),
            tier=ProliferatorTier.NONE,
            flow=flow,
        )
        (spec,) = pinned.candidates

        assert spec.label == "flow-pinned"
        assert not spec.is_proliferated
        assert all(not item_id.startswith("proliferator-") for item_id in spec.external_inputs)

    def test_no_flow_keeps_all_frontier_choices(self, data: Dataset) -> None:
        labels = {spec.label for spec in build_candidates(data, parse_url(URL), count=3).candidates}
        assert labels == {"no-proliferator", "all-products", "output-products"}
