"""Every bound on a submitted build is a refusal, never a clamp."""

from __future__ import annotations

import pytest

from flab2bp import pipeline
from flab2bp.rates import DEFAULT_CANDIDATE_POLICIES, CandidatePolicy
from flab2bp.web.jobs import MAX_SOLVER_SECONDS, InvalidOptions, Options, parse_options
from flab2bp.web.payload import JsonValue

URL = "https://factoriolab.github.io/dsp/flow?o=graphene*60&v=11"


def test_fetch_flow_defaults_off_and_accepts_the_factorio_lab_origin() -> None:
    assert parse_options({"url": URL}).fetch_flow is False
    assert parse_options({"url": URL, "fetch_flow": True}).fetch_flow is True


@pytest.mark.parametrize("value", [1, "yes", None, []])
def test_fetch_flow_requires_a_boolean(value: JsonValue) -> None:
    with pytest.raises(InvalidOptions, match="'fetch_flow' must be a boolean"):
        parse_options({"url": URL, "fetch_flow": value})


def test_web_fetch_and_supplied_flow_are_mutually_exclusive() -> None:
    with pytest.raises(InvalidOptions, match="flow.*fetch_flow"):
        parse_options({"url": URL, "flow": "Recipes\n", "fetch_flow": True})


@pytest.mark.parametrize(
    "url",
    [
        r"https://127.0.0.1\@factoriolab.github.io/dsp/flow?v=11&o=x",
        "https://user@factoriolab.github.io/dsp/flow?v=11&o=x",
    ],
)
def test_web_fetch_rejects_ambiguous_or_authenticated_authorities(url: str) -> None:
    with pytest.raises(InvalidOptions, match="FactorioLab HTTPS"):
        parse_options({"url": url, "fetch_flow": True})


@pytest.mark.parametrize(
    "url",
    [
        "https://[factoriolab.github.io/dsp/flow?v=11&o=x",
        "https://factoriolab.github.io／example.com/dsp/flow?v=11&o=x",
    ],
)
def test_web_fetch_translates_malformed_authorities_to_invalid_options(url: str) -> None:
    with pytest.raises(InvalidOptions, match="FactorioLab HTTPS"):
        parse_options({"url": url, "fetch_flow": True})


@pytest.mark.parametrize(
    "url",
    [
        "http://factoriolab.github.io/dsp/flow?o=x&v=11",
        "https://example.com/dsp/flow?o=x&v=11",
        "https://factoriolab.github.io:444/dsp/flow?o=x&v=11",
        "https://factoriolab.github.io/dsp/other?o=x&v=11",
        "https://factoriolab.github.io:bad/dsp/flow?o=x&v=11",
    ],
)
def test_web_fetch_rejects_navigation_outside_supported_pages(url: str) -> None:
    with pytest.raises(InvalidOptions, match="FactorioLab HTTPS"):
        parse_options({"url": url, "fetch_flow": True})


def test_defaults_match_the_cli() -> None:
    options = parse_options({"url": URL})
    assert (options.strategy, options.candidate_policies, options.budget_s) == (
        "best",
        DEFAULT_CANDIDATE_POLICIES,
        15.0,
    )
    assert options.proliferator_tier is None
    assert not hasattr(options, "power")
    # The CLI refuses to emit an invalid blueprint unless asked; so does this.
    assert options.allow_invalid is False


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        (
            ["all-products", "output-products", "no-proliferator"],
            DEFAULT_CANDIDATE_POLICIES,
        ),
        (
            ["output-products"],
            (CandidatePolicy.OUTPUT_PRODUCTS,),
        ),
        (
            ["output-products", "no-proliferator"],
            (
                CandidatePolicy.NO_PROLIFERATOR,
                CandidatePolicy.OUTPUT_PRODUCTS,
            ),
        ),
    ],
)
def test_candidate_policy_subsets_are_exact_and_canonical(
    selection: list[JsonValue],
    expected: tuple[CandidatePolicy, ...],
) -> None:
    options = parse_options({"url": URL, "candidate_policies": selection})
    assert options.candidate_policies == expected


@pytest.mark.parametrize(
    "selection",
    [
        [],
        ["no-proliferator", "no-proliferator"],
        [1],
        ["unknown"],
        "all-products",
    ],
)
def test_invalid_candidate_policy_selections_are_refused(selection: JsonValue) -> None:
    with pytest.raises(InvalidOptions, match="candidate_policies"):
        parse_options({"url": URL, "candidate_policies": selection})


@pytest.mark.parametrize("count", [0, 1, 3, True])
def test_legacy_numeric_candidate_field_is_rejected(count: int | bool) -> None:
    with pytest.raises(InvalidOptions, match="unknown option.*candidates"):
        parse_options({"url": URL, "candidates": count})


@pytest.mark.parametrize("legacy_power", [False, True])
def test_legacy_power_option_is_rejected(legacy_power: bool) -> None:
    with pytest.raises(InvalidOptions, match="power"):
        parse_options({"url": URL, "power": legacy_power})


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": "   "},
        {"url": URL, "strategy": "greedy"},
        {"url": URL, "strategy": "unknown"},
        {"url": URL, "candidates": 0},
        {"url": URL, "candidates": 9},
        {"url": URL, "candidates": 2.5},
        {"url": URL, "budget_s": 0},
        {"url": URL, "budget_s": -1},
        {"url": URL, "budget_s": float("nan")},
        {"url": URL, "budget_s": 10**10_000},
        {"url": URL, "power": "no"},
        {"url": URL, "allow_invalid": "yes"},
        {"url": URL, "name": 7},
        "not an object",
    ],
)
def test_bad_requests_are_refused(body: JsonValue) -> None:
    with pytest.raises(InvalidOptions):
        parse_options(body)


def test_proliferator_tier_is_optional_and_explicit() -> None:
    from flab2bp.rates.adjust import ProliferatorTier

    assert (
        parse_options({"url": URL, "proliferator_tier": "1"}).proliferator_tier
        is ProliferatorTier.MK1
    )
    assert (
        parse_options({"url": URL, "proliferator_tier": "2"}).proliferator_tier
        is ProliferatorTier.MK2
    )
    assert (
        parse_options({"url": URL, "proliferator_tier": "3"}).proliferator_tier
        is ProliferatorTier.MK3
    )
    assert (
        parse_options({"url": URL, "proliferator_tier": "none"}).proliferator_tier
        is ProliferatorTier.NONE
    )
    assert parse_options({"url": URL, "proliferator_tier": "auto"}).proliferator_tier is None
    with pytest.raises(InvalidOptions, match="proliferator_tier"):
        parse_options({"url": URL, "proliferator_tier": "4"})


def test_web_strategies_are_the_public_subset() -> None:
    assert parse_options({"url": URL, "strategy": "freeform"}).strategy == "freeform"
    assert parse_options({"url": URL, "strategy": "sequence-pair"}).strategy == "sequence-pair"


def test_the_candidate_policy_ceiling_is_on_the_product_not_the_budget() -> None:
    """The ceiling follows the selected policies and strategies actually run."""
    best_budget = MAX_SOLVER_SECONDS / (
        len(DEFAULT_CANDIDATE_POLICIES) * pipeline.PRODUCTION_STRATEGY_COUNT
    )
    at_the_edge = parse_options(
        {
            "url": URL,
            "candidate_policies": [policy.value for policy in DEFAULT_CANDIDATE_POLICIES],
            "budget_s": best_budget,
        }
    )
    assert at_the_edge.solver_ceiling_s == pytest.approx(MAX_SOLVER_SECONDS)

    with pytest.raises(InvalidOptions, match="ceiling"):
        parse_options(
            {
                "url": URL,
                "candidate_policies": [policy.value for policy in DEFAULT_CANDIDATE_POLICIES],
                "budget_s": best_budget + 1.0,
            }
        )


def test_best_ceiling_follows_the_selected_candidate_policy_subset() -> None:
    best = Options(
        url=URL,
        strategy="best",
        candidate_policies=(
            CandidatePolicy.NO_PROLIFERATOR,
            CandidatePolicy.ALL_PRODUCTS,
        ),
        budget_s=5.0,
    )
    expected = 2 * pipeline.PRODUCTION_STRATEGY_COUNT * 5.0
    assert best.solver_ceiling_s == expected


def test_explicit_strategy_ceiling_is_one_layout_per_candidate_policy() -> None:
    sequence_pair = Options(
        url=URL,
        strategy="sequence-pair",
        candidate_policies=(
            CandidatePolicy.NO_PROLIFERATOR,
            CandidatePolicy.ALL_PRODUCTS,
        ),
        budget_s=5.0,
    )
    assert sequence_pair.solver_ceiling_s == 10.0


@pytest.mark.parametrize(
    "pin",
    [
        {"flow": "Recipes\nid,name\ngraphene,Graphene\n"},
        {"fetch_flow": True},
    ],
)
def test_pinned_flow_effective_candidate_count_and_ceiling_are_one(
    pin: dict[str, JsonValue],
) -> None:
    options = parse_options(
        {
            "url": URL,
            "candidate_policies": [policy.value for policy in DEFAULT_CANDIDATE_POLICIES],
            "budget_s": 5.0,
            **pin,
        }
    )
    assert options.effective_candidate_count == 1
    assert options.solver_ceiling_s == pipeline.PRODUCTION_STRATEGY_COUNT * 5.0


def test_candidate_ceiling_error_reports_the_effective_pinned_count() -> None:
    with pytest.raises(InvalidOptions, match=r"1 candidate\(s\)"):
        parse_options(
            {
                "url": URL,
                "fetch_flow": True,
                "budget_s": MAX_SOLVER_SECONDS,
            }
        )


class TestFlowIsAnOptionNow:
    """``--flow``, as CSV text rather than a path.

    The CLI names a file; a browser pastes or uploads one.  Both reach
    ``flow_from_text`` and its provenance check, so neither can acquire a
    pinned selection without the URL having been verified.
    """

    def test_absent_means_derived_not_pinned(self) -> None:
        assert parse_options({"url": URL}).flow == ""

    def test_the_csv_text_is_carried_whole(self) -> None:
        csv = "Recipes\nid,name\ngraphene,Graphene\n"
        assert parse_options({"url": URL, "flow": csv}).flow == csv.strip()

    def test_a_non_string_flow_is_a_refusal(self) -> None:
        with pytest.raises(InvalidOptions, match="'flow' must be a string"):
            parse_options({"url": URL, "flow": ["a", "b"]})

    def test_whitespace_only_is_the_same_as_absent(self) -> None:
        # Otherwise an empty textarea would submit a "flow" that parses to
        # nothing and refuses, instead of the derived build the user asked for.
        assert parse_options({"url": URL, "flow": "  \n\t "}).flow == ""
