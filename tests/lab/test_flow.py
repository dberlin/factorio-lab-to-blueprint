"""Reading FactorioLab's flow export, and pinning our selection to it.

The property under test throughout is that **FactorioLab's recipe choice wins**.
Every test that claims a pin works is paired with evidence the same assertion
fails without it -- ``test_unpinned_picks_a_different_selection`` is that
evidence for the central case, and it is the reason these tests are worth
having: an assertion that passes whether or not the pin is applied proves
nothing about the pin.

These are fast by construction.  The only solver call is a four-recipe URL that
runs in well under a second; the parser tests cost milliseconds.
"""

from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import (
    FlowFormatError,
    FlowNode,
    FlowProvenanceError,
    FlowSelection,
    FlowSelectionError,
    compare_selection,
    load_flow,
    parse_flow_json,
    pin_request,
    pinned_exclusions,
    verify_against_request,
)
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.solve import solve

FIXTURE = Path(__file__).parent.parent / "fixtures" / "flow_graphene_advanced.json"

#: The corpus's `graphene` URL.  Chosen because graphene is the canonical
#: multiple-producer item in DSP -- `graphene` (energetic graphite + sulfuric
#: acid) against `graphene-advanced` (fire ice) -- and the two differ in their
#: external inputs, so the pin is observable at the blueprint's boundary rather
#: than only in the recipe list.
GRAPHENE_URL = (
    "https://factoriolab.github.io/dsp/list?o=graphene*60&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
)


@pytest.fixture(scope="module")
def data() -> Dataset:
    return load_vendored()


def _flow(*node_ids: str) -> FlowSelection:
    return FlowSelection(
        nodes=tuple(
            FlowNode(kind=n.split("|", 1)[0], ref_id=n.split("|", 1)[1]) for n in node_ids
        )
    )


class TestParse:
    def test_reads_the_recipe_selection(self) -> None:
        flow = load_flow(FIXTURE)
        assert flow.chosen_recipe_ids == {"graphene-advanced", "fire-ice-vein"}

    def test_surplus_is_not_a_demand(self) -> None:
        """`s|hydrogen` marks a byproduct nobody consumes.

        Reading it as something to belt in is the failure mode that motivated
        the initiative in the first place.
        """
        flow = load_flow(FIXTURE)
        assert flow.surplus_item_ids == {"hydrogen"}
        assert flow.output_item_ids == {"graphene"}

    def test_machine_choice_is_recovered_from_the_icon(self, data: Dataset) -> None:
        """`icon.id` is a machine id on a recipe node -- but only sometimes.

        Accepted only when the dataset resolves it as a machine, so the check
        verifies itself rather than trusting the field's position.
        """
        assert load_flow(FIXTURE).machines(data) == {
            "graphene-advanced": "chemical-plant",
            "fire-ice-vein": "mining-machine",
        }

    def test_item_nodes_are_known_to_be_incomplete(self) -> None:
        """`fire-ice` feeds one recipe, so buildGraph prunes its item node.

        Pinned here because it is the reason nothing may test membership of
        `item_ids` to decide an item is absent from the flow.
        """
        flow = load_flow(FIXTURE)
        assert "fire-ice" not in flow.item_ids
        assert "fire-ice-vein" in flow.chosen_recipe_ids

    @pytest.mark.parametrize(
        ("text", "because"),
        [
            ("not json at all", "not valid JSON"),
            ("[]", "expected a JSON object"),
            ('{"links": []}', "no 'nodes' array"),
            ('{"nodes": [{"id": "graphene"}]}', "is not '<kind>|<id>'"),
            ('{"nodes": [{"id": "x|graphene"}]}', "does not emit"),
            ('{"nodes": [{"id": "i|"}]}', "names nothing"),
            ('{"nodes": [{"id": "i|graphene"}]}', "no recipe nodes"),
        ],
    )
    def test_refuses_rather_than_guesses(self, text: str, because: str) -> None:
        with pytest.raises(FlowFormatError, match=because):
            parse_flow_json(text)

    def test_a_missing_file_refuses(self, tmp_path: Path) -> None:
        with pytest.raises(FlowFormatError, match="cannot read flow export"):
            load_flow(tmp_path / "nope.json")

    def test_links_are_validated_too(self) -> None:
        bad = json.dumps(
            {"nodes": [{"id": "r|graphene"}], "links": [{"source": "r|graphene", "target": "?"}]}
        )
        with pytest.raises(FlowFormatError, match="is not '<kind>|<id>'"):
            parse_flow_json(bad)


class TestPin:
    def test_unpinned_picks_a_different_selection(self, data: Dataset) -> None:
        """The instrument check: without a flow we choose the OTHER recipe.

        If this ever stops holding, every "the pin worked" assertion below
        becomes vacuous, so it is asserted rather than assumed.
        """
        plan = solve(data, parse_url(GRAPHENE_URL))
        chosen = {g.recipe_id for g in plan.groups}
        assert "graphene" in chosen and "graphene-advanced" not in chosen
        assert set(plan.external_inputs) == {"coal", "crude-oil", "stone", "water"}

    def test_pinning_moves_the_boundary(self, data: Dataset) -> None:
        """The whole point: FactorioLab's choice changes what gets belted in.

        `graphene-advanced` takes fire ice, which only mining recipes make, so
        the blueprint's inputs become {fire-ice} rather than the four the
        unpinned solve asks for. Belting in stone for a flow containing none is
        the bug this prevents.
        """
        request = pin_request(parse_url(GRAPHENE_URL), data, load_flow(FIXTURE))
        plan = solve(data, request)
        assert {g.recipe_id for g in plan.groups} == {"graphene-advanced"}
        assert dict(plan.external_inputs) == {"fire-ice": Fraction(1)}
        # Exact, and hand-checkable: graphene-advanced makes 2 graphene per
        # 2-second craft, so one chemical plant delivers the 60/min objective.
        assert plan.groups[0].exact_machines == Fraction(1)
        assert dict(plan.surplus) == {"hydrogen": Fraction(1, 2)}

    def test_the_pin_excludes_everything_not_chosen(self, data: Dataset) -> None:
        flow = load_flow(FIXTURE)
        excluded = pinned_exclusions(data, flow)
        assert excluded.isdisjoint(flow.chosen_recipe_ids)
        assert excluded | flow.chosen_recipe_ids == {r.id for r in data.recipes}

    def test_an_unbuildable_recipe_refuses(self, data: Dataset) -> None:
        with pytest.raises(FlowSelectionError, match="dataset does not define"):
            pinned_exclusions(data, _flow("r|no-such-recipe"))

    def test_no_flow_leaves_the_request_untouched(self, data: Dataset) -> None:
        """The corpus carries no flow file, so its behaviour must not move."""
        assert parse_url(GRAPHENE_URL).excluded_recipe_ids is None


class TestProvenance:
    def test_a_flow_that_cannot_make_the_objective_refuses(self, data: Dataset) -> None:
        with pytest.raises(FlowProvenanceError, match="which the flow does not produce"):
            verify_against_request(_flow("r|iron-ingot"), data, parse_url(GRAPHENE_URL))

    def test_a_recipe_the_url_explicitly_excludes_refuses(self, data: Dataset) -> None:
        """An EXPLICIT exclusion set is the player's UI state, so it contradicts.

        Set on the request directly rather than through `rex=`, which is
        hash-index encoded against the mod: how that encoding resolves is
        `test_url.py`'s subject, and going through it here would test the URL
        parser instead of the provenance rule.
        """
        request = replace(parse_url(GRAPHENE_URL), excluded_recipe_ids={"graphene-advanced"})
        with pytest.raises(FlowProvenanceError, match="this URL's own settings"):
            verify_against_request(load_flow(FIXTURE), data, request)

    def test_the_mods_defaults_may_not_contradict_the_flow(self, data: Dataset) -> None:
        """Absence is not emptiness -- the `60d5f0f` distinction.

        `graphene-advanced` and `fire-ice-vein` are both DEFAULT-excluded in
        DSP, and both are ordinary player choices. A URL that says nothing about
        recipes leaves us guessing with the defaults, and our guess may not
        overrule the player's actual flow. Checking against the defaults here
        re-created the original bug exactly.
        """
        assert {"graphene-advanced", "fire-ice-vein"} <= set(data.default_recipe_excluded)
        assert parse_url(GRAPHENE_URL).excluded_recipe_ids is None
        verify_against_request(load_flow(FIXTURE), data, parse_url(GRAPHENE_URL))


class TestCompareSelection:
    def test_a_reproduced_flow_reports_nothing(self, data: Dataset) -> None:
        flow = load_flow(FIXTURE)
        plan = solve(data, pin_request(parse_url(GRAPHENE_URL), data, flow))
        built = {g.recipe_id: g.machine_item_id for g in plan.groups}
        assert compare_selection(flow, data, built=built) == ()

    def test_mining_recipes_are_not_a_difference(self, data: Dataset) -> None:
        """`fire-ice-vein` is in the flow and never built here, by design."""
        flow = load_flow(FIXTURE)
        assert "fire-ice-vein" in flow.chosen_recipe_ids
        assert compare_selection(flow, data, built={"graphene-advanced": "chemical-plant"}) == ()

    def test_a_leak_is_named(self, data: Dataset) -> None:
        findings = compare_selection(load_flow(FIXTURE), data, built={"graphene": "chemical-plant"})
        assert any("graphene: we build it" in f for f in findings)
        assert any("graphene-advanced: the flow runs it" in f for f in findings)

    def test_a_different_machine_is_named(self, data: Dataset) -> None:
        findings = compare_selection(
            load_flow(FIXTURE), data, built={"graphene-advanced": "quantum-chemical-plant"}
        )
        assert any("in the flow" in f for f in findings)
