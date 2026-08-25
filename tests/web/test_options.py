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
