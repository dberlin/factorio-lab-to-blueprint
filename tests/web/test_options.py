"""Every bound on a submitted build is a refusal, never a clamp."""

from __future__ import annotations

import pytest

from flab2bp import pipeline
from flab2bp.web.jobs import MAX_SOLVER_SECONDS, InvalidOptions, Options, parse_options
from flab2bp.web.payload import JsonValue

URL = "https://factoriolab.github.io/dsp/flow?o=graphene*60&v=11"


def test_defaults_match_the_cli() -> None:
    options = parse_options({"url": URL})
    assert (options.strategy, options.candidates, options.budget_s) == ("best", 3, 15.0)
    assert options.proliferator_tier is None
    assert options.power is True
    # The CLI refuses to emit an invalid blueprint unless asked; so does this.
    assert options.allow_invalid is False


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


def test_booleans_are_not_integers() -> None:
    """``True`` is an ``int`` in Python, and ``candidates=True`` is not a count."""
    with pytest.raises(InvalidOptions):
        parse_options({"url": URL, "candidates": True})


def test_web_strategies_are_the_public_subset() -> None:
    assert parse_options({"url": URL, "strategy": "freeform"}).strategy == "freeform"
    assert parse_options({"url": URL, "strategy": "sequence-pair"}).strategy == "sequence-pair"


def test_the_ceiling_is_on_the_product_not_the_budget() -> None:
    """The ceiling follows the strategies that ``best`` actually runs."""
    best_budget = MAX_SOLVER_SECONDS / (3 * pipeline.PRODUCTION_STRATEGY_COUNT)
    at_the_edge = parse_options({"url": URL, "candidates": 3, "budget_s": best_budget})
    assert at_the_edge.solver_ceiling_s == pytest.approx(MAX_SOLVER_SECONDS)

    with pytest.raises(InvalidOptions, match="ceiling"):
        parse_options({"url": URL, "candidates": 3, "budget_s": best_budget + 1.0})


def test_best_ceiling_follows_the_canonical_production_portfolio() -> None:
    best = Options(url=URL, strategy="best", candidates=2, budget_s=5.0)
    expected = 2 * pipeline.PRODUCTION_STRATEGY_COUNT * 5.0
    assert best.solver_ceiling_s == expected


def test_explicit_strategy_ceiling_is_one_layout_per_candidate() -> None:
    sequence_pair = Options(url=URL, strategy="sequence-pair", candidates=2, budget_s=5.0)
    assert sequence_pair.solver_ceiling_s == 10.0


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
