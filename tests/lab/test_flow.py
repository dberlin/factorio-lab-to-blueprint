"""Reading FactorioLab's CSV export, and pinning our selection to it.

The property under test throughout is that **FactorioLab's recipe choice wins**.
Every test claiming a pin works is paired with evidence the same assertion fails
without it -- ``test_unpinned_picks_a_different_selection`` is that evidence for
the central case, and it is why these tests are worth having: an assertion that
passes whether or not the pin is applied proves nothing about the pin.

Two fixtures, and the difference between them is the point:

``flow_graphene_advanced.csv``
    A pristine export in the exporter's exact output format -- comma-delimited,
    quoted URL line, every numeric cell ``'=' + Rational.toString()``.  Exact
    throughout, so the magnitude cross-check is a real comparison.

``flow_spreadsheet_sample.tsv``
    A real export as a spreadsheet re-saved it: tab-delimited, no ``=``, URL
    unquoted, and every ``=p/q`` evaluated to a nine-place decimal.  Accepted,
    because it is what a user is most likely to hand over, but its rows are
    flagged inexact and the cross-check says so instead of inventing precision.

These are fast by construction: one four-recipe solve, everything else parsing.
"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from flab2bp.lab import flow as flow_module
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import (
    FlowFormatError,
    FlowProvenanceError,
    FlowRow,
    FlowSelection,
    FlowSelectionError,
    cross_check,
    load_flow,
    parse_flow_csv,
    pin_request,
    pinned_exclusions,
    unsupplied_inputs,
    verify_against_request,
    verify_provenance,
)
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.solve import solve

FIXTURES = Path(__file__).parent.parent / "fixtures"
PRISTINE = FIXTURES / "flow_graphene_advanced.csv"
MANGLED = FIXTURES / "flow_spreadsheet_sample.tsv"

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


@pytest.fixture(scope="module")
def pristine() -> FlowSelection:
    return load_flow(PRISTINE, url=GRAPHENE_URL)


@pytest.fixture(scope="module")
def mangled() -> FlowSelection:
    return parse_flow_csv(MANGLED.read_text())


def _csv(*rows: str, url: str = GRAPHENE_URL, header: str = "Item,Items,Recipe") -> str:
    return "\r\n".join([f'"{url}"', header, *rows]) + "\r\n"


class TestParseExactly:
    def test_reads_the_recipe_selection(self, pristine: FlowSelection) -> None:
        assert pristine.chosen_recipe_ids == {"graphene-advanced", "fire-ice-vein"}

    def test_numbers_are_exact_fractions_never_floats(self, pristine: FlowSelection) -> None:
        """The rule the whole module exists to keep.

        A float here sizes a belt wrong and ships a blueprint that quietly
        misses its rate, so the type is asserted, not just the value.
        """
        row = pristine.by_item["graphene"]
        assert row.items == Fraction(60) and type(row.items) is Fraction
        assert row.machines == Fraction(1) and type(row.machines) is Fraction
        assert pristine.by_recipe["fire-ice-vein"].machines == Fraction(3, 4)
        assert pristine.is_exact

    def test_a_decimal_cell_goes_through_fraction_not_float(self) -> None:
        """`Fraction("0.1")` is 1/10; `Fraction(float("0.1"))` is not.

        Deliberately a value binary floating point cannot represent, because
        every integer and every n/2^k -- which is what the rest of these
        fixtures happen to use -- round-trips through a float unchanged and so
        proves nothing. A mutation replacing `Fraction(text)` with
        `Fraction(float(text))` survived the whole suite until this test
        existed, which is exactly the instrument check the house rules ask for.
        """
        flow = parse_flow_csv(_csv("water,=0.1,water-pump"))
        assert flow.by_item["water"].items == Fraction(1, 10)

    def test_p_over_q_survives_where_a_float_would_not(self) -> None:
        """`=2161/3571` is not representable as a float; it must stay exact."""
        flow = parse_flow_csv(_csv("coal,=2161/3571,coal-vein"))
        assert flow.by_item["coal"].items == Fraction(2161, 3571)

    def test_a_spreadsheet_round_trip_is_accepted_and_flagged(
        self, mangled: FlowSelection
    ) -> None:
        """Tab-delimited, no `=`, unquoted URL, fractions evaluated to decimals.

        Still parsed -- refusing it would reject the file most users have -- but
        every mangled row is marked so nothing downstream treats it as exact.
        """
        assert not mangled.is_exact
        assert mangled.by_item["graphene"].machines == Fraction(5, 2)
        assert not mangled.by_item["fire-ice"].exact
        # Mangled is not the same as approximated: the decimal a spreadsheet
        # wrote is still read exactly as written, so what we hold is precisely
        # what the file says and the loss is attributed to the spreadsheet
        # rather than compounded by us.
        assert mangled.by_item["energetic-graphite"].items == Fraction(219168357, 2000000)
        # 450 and 0.625 both round-trip through toFixed(3), so this row really
        # is exact even in a mangled file. Precision is judged per value.
        assert mangled.by_item["titanium-ingot"].exact

    def test_surplus_is_not_a_demand(self, mangled: FlowSelection) -> None:
        """`Items 0 / Surplus 125` is a byproduct nobody consumes.

        Reading it as a demand would put a belt of hydrogen into the inputs,
        which is the failure class the initiative exists to remove.
        """
        row = mangled.by_item["hydrogen"]
        assert row.items == 0 and row.surplus == Fraction(125)
        assert not row.is_demand

    def test_external_inputs_are_the_flows_own_statement(
        self, mangled: FlowSelection, data: Dataset
    ) -> None:
        """Two ways in: a mining recipe, or no recipe at all.

        `ice-giant-gas-hydrate` is mining-flagged so fire ice arrives on a belt;
        `titanium-ingot` names no recipe, an Input objective. Hydrogen is
        surplus and must not appear.
        """
        assert mangled.external_items(data) == {
            "fire-ice": Fraction(150),
            "titanium-ingot": Fraction(450),
        }

    def test_ragged_rows_are_normal(self, mangled: FlowSelection) -> None:
        """The exporter stops a row at its last filled column."""
        assert mangled.by_item["titanium-ingot"].recipe_id == ""
        assert mangled.by_item["titanium-ingot"].items == Fraction(450)

    @pytest.mark.parametrize(
        ("text", "because"),
        [
            ("", "at least a URL line"),
            ("Item,Items,Recipe\ngraphene,=60,graphene", "not a URL"),
            ('"https://x/dsp/list?v=11"\nItem;Items', "no comma or tab"),
            ('"https://x/dsp/list?v=11"\nItem,Nonsense\ng,1', "does not\nemit"),
            ('"https://x/dsp/list?v=11"\nItems,Belts\n=1,=1', "neither 'Item' nor 'Recipe'"),
            ('"https://x/dsp/list?v=11"\nItem,Items\n', "no steps"),
        ],
    )
    def test_refuses_rather_than_guesses(self, text: str, because: str) -> None:
        with pytest.raises(FlowFormatError, match=because.replace("\n", " ")):
            parse_flow_csv(text)

    def test_an_unparseable_number_refuses(self) -> None:
        """Better to refuse than to invent a rate from a cell we cannot read."""
        with pytest.raises(FlowFormatError, match="is not a number FactorioLab writes"):
            parse_flow_csv(_csv("graphene,=1.2.3,graphene"))

    def test_a_duplicated_item_refuses(self) -> None:
        with pytest.raises(FlowFormatError, match="appears on two rows"):
            parse_flow_csv(_csv("graphene,=60,graphene", "graphene,=60,graphene-advanced"))

    def test_too_many_fields_refuses(self) -> None:
        with pytest.raises(FlowFormatError, match="fields but the header has"):
            parse_flow_csv(_csv("graphene,=60,graphene,extra"))

    def test_a_missing_file_refuses(self, tmp_path: Path) -> None:
        with pytest.raises(FlowFormatError, match="cannot read flow export"):
            load_flow(tmp_path / "nope.csv", url=GRAPHENE_URL)


class TestProvenance:
    """Line 1 carries `window.location.href`; it is why the CSV is the path."""

    def test_a_different_url_refuses_and_says_what_differs(
        self, pristine: FlowSelection
    ) -> None:
        other = GRAPHENE_URL.replace("graphene*60", "graphene*120")
        with pytest.raises(FlowProvenanceError, match="different URL") as exc:
            verify_provenance(pristine, other)
        assert "parameter 'o'" in str(exc.value)

    def test_a_different_host_refuses(self, pristine: FlowSelection) -> None:
        elsewhere = GRAPHENE_URL.replace("factoriolab.github.io", "evil.example")
        with pytest.raises(FlowProvenanceError, match="origin"):
            verify_provenance(pristine, elsewhere)

    def test_a_different_mod_refuses(self, pristine: FlowSelection) -> None:
        with pytest.raises(FlowProvenanceError, match="mod path"):
            verify_provenance(pristine, GRAPHENE_URL.replace("/dsp/", "/1.1/"))

    def test_the_view_segment_is_not_a_difference(self, pristine: FlowSelection) -> None:
        """`/list` and `/flow` are one solved state seen two ways.

        The download button is reachable from both, so refusing here would deny
        a player their own export.
        """
        verify_provenance(pristine, GRAPHENE_URL.replace("/dsp/list?", "/dsp/flow?"))

    def test_reordered_parameters_are_not_a_difference(self, pristine: FlowSelection) -> None:
        """Angular's router reorders them; the state is identical."""
        verify_provenance(pristine, GRAPHENE_URL.replace("?o=graphene*60&", "?v=11&o=graphene*60&")
                          .replace("&v=11", ""))

    def test_no_url_refuses_rather_than_assumes(self, pristine: FlowSelection) -> None:
        with pytest.raises(FlowProvenanceError, match="cannot be established"):
            verify_provenance(pristine, "  ")

    def test_load_flow_checks_provenance(self) -> None:
        with pytest.raises(FlowProvenanceError):
            load_flow(PRISTINE, url=GRAPHENE_URL.replace("graphene*60", "iron-ingot*60"))


class TestStructuralAgreement:
    def test_a_flow_that_cannot_make_the_objective_refuses(self, data: Dataset) -> None:
        flow = FlowSelection(GRAPHENE_URL, (FlowRow(item_id="iron-ingot", recipe_id="iron-ingot"),))
        with pytest.raises(FlowProvenanceError, match="which the flow does not produce"):
            verify_against_request(flow, data, parse_url(GRAPHENE_URL))

    def test_a_recipe_the_url_explicitly_excludes_refuses(
        self, pristine: FlowSelection, data: Dataset
    ) -> None:
        """An EXPLICIT exclusion set is the player's UI state, so it contradicts.

        Set on the request directly rather than through `rex=`, which is
        hash-index encoded against the mod: how that resolves is `test_url.py`'s
        subject, and going through it here would test the URL parser instead.
        """
        request = replace(parse_url(GRAPHENE_URL), excluded_recipe_ids={"graphene-advanced"})
        with pytest.raises(FlowProvenanceError, match="this URL's own settings"):
            verify_against_request(pristine, data, request)

    def test_the_mods_defaults_may_not_contradict_the_flow(
        self, pristine: FlowSelection, data: Dataset
    ) -> None:
        """Absence is not emptiness -- the `60d5f0f` distinction.

        `graphene-advanced` and `fire-ice-vein` are both DEFAULT-excluded in DSP
        and both are ordinary player choices. A URL saying nothing about recipes
        leaves us guessing with the defaults, and our guess may not overrule the
        player's actual flow. Checking against the defaults re-created the
        original bug exactly, and this test caught it.
        """
        assert {"graphene-advanced", "fire-ice-vein"} <= set(data.default_recipe_excluded)
        assert parse_url(GRAPHENE_URL).excluded_recipe_ids is None
        verify_against_request(pristine, data, parse_url(GRAPHENE_URL))


class TestPin:
    def test_unpinned_picks_a_different_selection(self, data: Dataset) -> None:
        """The instrument check: without a flow we choose the OTHER recipe.

        If this stops holding, every "the pin worked" assertion below becomes
        vacuous, so it is asserted rather than assumed.
        """
        plan = solve(data, parse_url(GRAPHENE_URL))
        chosen = {g.recipe_id for g in plan.groups}
        assert "graphene" in chosen and "graphene-advanced" not in chosen
        assert set(plan.external_inputs) == {"coal", "sulfuric-acid"}

    def test_pinning_moves_the_boundary(self, pristine: FlowSelection, data: Dataset) -> None:
        """The whole point: FactorioLab's choice changes what gets belted in.

        `graphene-advanced` takes fire ice, which only mining recipes make, so
        the inputs become {fire-ice} rather than the four the unpinned solve
        asks for. Belting in stone for a flow containing none is the bug this
        prevents.
        """
        plan = solve(data, pin_request(parse_url(GRAPHENE_URL), data, pristine))
        assert {g.recipe_id for g in plan.groups} == {"graphene-advanced"}
        assert dict(plan.external_inputs) == {"fire-ice": Fraction(1)}
        # Exact and hand-checkable: graphene-advanced makes 2 graphene per
        # 2-second craft, so one chemical plant delivers the 60/min objective.
        assert plan.groups[0].exact_machines == Fraction(1)
        assert dict(plan.surplus) == {"hydrogen": Fraction(1, 2)}

    def test_direct_pin_adapter_canonicalizes_exactly_once(
        self,
        pristine: FlowSelection,
        data: Dataset,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        request = parse_url(GRAPHENE_URL)
        canonical_data = flow_module.canonicalize_dataset(data)
        canonical_request = flow_module.canonicalize_request(request)
        assert hasattr(flow_module, "_pin_request_canonical")
        calls = {"dataset": 0, "request": 0}

        def canonical_data_spy(source: Dataset) -> Dataset:
            assert source is data
            calls["dataset"] += 1
            return canonical_data

        def canonical_request_spy(source: object) -> object:
            assert source is request
            calls["request"] += 1
            return canonical_request

        def internal(request_arg: object, data_arg: object, selection: object) -> object:
            assert request_arg is canonical_request
            assert data_arg is canonical_data
            assert selection is pristine
            return canonical_request

        monkeypatch.setattr(flow_module, "canonicalize_dataset", canonical_data_spy)
        monkeypatch.setattr(flow_module, "canonicalize_request", canonical_request_spy)
        monkeypatch.setattr(flow_module, "_pin_request_canonical", internal)

        assert flow_module.pin_request(request, data, pristine) is canonical_request
        assert calls == {"dataset": 1, "request": 1}

    def test_the_pin_excludes_everything_not_chosen(
        self, pristine: FlowSelection, data: Dataset
    ) -> None:
        excluded = pinned_exclusions(data, pristine)
        assert excluded.isdisjoint(pristine.chosen_recipe_ids)
        assert excluded | pristine.chosen_recipe_ids == {r.id for r in data.recipes}

    def test_an_unbuildable_recipe_refuses(self, data: Dataset) -> None:
        flow = FlowSelection(GRAPHENE_URL, (FlowRow(item_id="x", recipe_id="no-such-recipe"),))
        with pytest.raises(FlowSelectionError, match="dataset does not define"):
            pinned_exclusions(data, flow)

    def test_no_flow_leaves_the_request_untouched(self) -> None:
        """The corpus carries no export, so its behaviour must not move."""
        assert parse_url(GRAPHENE_URL).excluded_recipe_ids is None


class TestCrossCheck:
    """The exact magnitude comparison the JSON export could not support."""

    def _ours(self, data: Dataset, pristine: FlowSelection) -> object:
        return solve(data, pin_request(parse_url(GRAPHENE_URL), data, pristine))

    def test_a_reproduced_flow_reports_nothing(
        self, pristine: FlowSelection, data: Dataset
    ) -> None:
        plan = solve(data, pin_request(parse_url(GRAPHENE_URL), data, pristine))
        assert cross_check(
            pristine,
            data,
            machines={g.recipe_id: g.machines for g in plan.groups},
            machine_items={g.recipe_id: g.machine_item_id for g in plan.groups},
            external_inputs=plan.external_inputs,
            outputs=dict(plan.outputs),
        ) == ()

    def test_a_wrong_machine_count_is_named(
        self, pristine: FlowSelection, data: Dataset
    ) -> None:
        findings = cross_check(
            pristine,
            data,
            machines={"graphene-advanced": 3},
            machine_items={"graphene-advanced": "chemical-plant"},
            external_inputs={"fire-ice": Fraction(1)},
        )
        assert any("3 machine(s) here, ceil(1) = 1 in the flow" in f for f in findings)

    def test_a_wrong_rate_is_named_exactly(
        self, pristine: FlowSelection, data: Dataset
    ) -> None:
        """Both sides exact, so a difference is real -- not a rounding artefact."""
        findings = cross_check(
            pristine,
            data,
            machines={"graphene-advanced": 1},
            machine_items={"graphene-advanced": "chemical-plant"},
            external_inputs={"fire-ice": Fraction(3, 2)},
        )
        assert any("we belt in 3/2/s; the flow uses 1/s" in f for f in findings)

    def test_a_wrong_machine_is_named(self, pristine: FlowSelection, data: Dataset) -> None:
        findings = cross_check(
            pristine,
            data,
            machines={"graphene-advanced": 1},
            machine_items={"graphene-advanced": "quantum-chemical-plant"},
            external_inputs={"fire-ice": Fraction(1)},
        )
        assert any("in the flow" in f and "quantum-chemical-plant" in f for f in findings)

    def test_mining_recipes_are_not_a_difference(
        self, pristine: FlowSelection, data: Dataset
    ) -> None:
        """`fire-ice-vein` is in the flow and never built here, by design."""
        findings = cross_check(
            pristine,
            data,
            machines={"graphene-advanced": 1},
            machine_items={"graphene-advanced": "chemical-plant"},
            external_inputs={"fire-ice": Fraction(1)},
        )
        assert not any("fire-ice-vein" in f for f in findings)

    def test_a_mangled_row_cannot_settle_a_difference(
        self, mangled: FlowSelection, data: Dataset
    ) -> None:
        """A check that degrades to "close enough" is how a rate defect ships.

        The row lost precision in a spreadsheet, so the divergence is reported
        as unconfirmable rather than either asserted or silently tolerated.
        """
        # The flow's own figure is 150/min, i.e. exactly 5/2 per second, so 3/s
        # is a genuine divergence -- but `fire-ice`'s row was mangled, so the
        # file cannot settle it.
        findings = cross_check(
            mangled, data, machines={}, machine_items={}, external_inputs={"fire-ice": Fraction(3)}
        )
        assert any("lost precision in a spreadsheet" in f for f in findings)

    def test_an_intact_row_in_a_mangled_file_still_compares(
        self, mangled: FlowSelection, data: Dataset
    ) -> None:
        """Precision is judged per value, not per file.

        `titanium-ingot` is 450/min = 15/2 per second and survived intact, so a
        divergence on it is stated outright rather than hedged.
        """
        findings = cross_check(
            mangled,
            data,
            machines={},
            machine_items={},
            external_inputs={"titanium-ingot": Fraction(8)},
        )
        assert any("we belt in 8/s; the flow uses 15/2/s" in f for f in findings)


class TestBoundaryRule:
    def test_an_input_the_flow_does_not_have_is_caught(
        self, pristine: FlowSelection, data: Dataset
    ) -> None:
        """The stone bug, stated directly.

        The flow belts in fire ice and nothing else; a build asking for stone
        has changed FactorioLab's chosen inputs, which may never happen.
        """
        stray = unsupplied_inputs(
            pristine, data, {"fire-ice": Fraction(1), "stone": Fraction(1)}
        )
        assert stray == ("stone",)

    def test_a_faithful_build_has_no_stray_inputs(
        self, pristine: FlowSelection, data: Dataset
    ) -> None:
        plan = solve(data, pin_request(parse_url(GRAPHENE_URL), data, pristine))
        assert unsupplied_inputs(pristine, data, plan.external_inputs) == ()

    def test_proliferator_is_the_one_exemption(
        self, pristine: FlowSelection, data: Dataset
    ) -> None:
        """FactorioLab builds it; we belt it in. Separate, known work."""
        inputs = {"fire-ice": Fraction(1), "proliferator-3": Fraction(1)}
        assert unsupplied_inputs(pristine, data, inputs) == ("proliferator-3",)
        assert unsupplied_inputs(
            pristine, data, inputs, exempt=frozenset({"proliferator-3"})
        ) == ()
