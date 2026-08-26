"""Every bound on a submitted build is a refusal, never a clamp."""

from __future__ import annotations

import pytest

from flab2bp.web.jobs import MAX_SOLVER_SECONDS, InvalidOptions, Options, parse_options

URL = "https://factoriolab.github.io/dsp/flow?o=graphene*60&v=11"


def test_defaults_match_the_cli() -> None:
    options = parse_options({"url": URL})
    assert (options.strategy, options.candidates, options.budget_s) == ("best", 3, 2.0)
    assert options.power is True
    # The CLI refuses to emit an invalid blueprint unless asked; so does this.
    assert options.allow_invalid is False


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": "   "},
        {"url": URL, "strategy": "greedy"},
        {"url": URL, "candidates": 0},
        {"url": URL, "candidates": 9},
        {"url": URL, "candidates": 2.5},
        {"url": URL, "budget_s": 0},
        {"url": URL, "budget_s": -1},
        {"url": URL, "power": "no"},
        {"url": URL, "allow_invalid": "yes"},
        {"url": URL, "name": 7},
        "not an object",
    ],
)
def test_bad_requests_are_refused(body: object) -> None:
    with pytest.raises(InvalidOptions):
        parse_options(body)


def test_booleans_are_not_integers() -> None:
    """``True`` is an ``int`` in Python, and ``candidates=True`` is not a count."""
    with pytest.raises(InvalidOptions):
        parse_options({"url": URL, "candidates": True})


def test_the_ceiling_is_on_the_product_not_the_budget() -> None:
    """Three candidates and both strategies at 60s is six minutes, not one."""
    at_the_edge = parse_options({"url": URL, "candidates": 3, "budget_s": 50.0})
    assert at_the_edge.solver_ceiling_s == pytest.approx(MAX_SOLVER_SECONDS)

    with pytest.raises(InvalidOptions, match="ceiling"):
        parse_options({"url": URL, "candidates": 3, "budget_s": 51.0})

    # The same budget is fine with one strategy, because half as much runs.
    assert parse_options({"url": URL, "candidates": 3, "budget_s": 51.0, "strategy": "spine"})


def test_ceiling_counts_both_strategies_for_best() -> None:
    single = Options(url=URL, strategy="spine", candidates=2, budget_s=5.0)
    both = Options(url=URL, strategy="best", candidates=2, budget_s=5.0)
    assert single.solver_ceiling_s == 10.0
    assert both.solver_ceiling_s == 20.0


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
