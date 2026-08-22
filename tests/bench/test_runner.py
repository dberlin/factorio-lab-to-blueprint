"""End-to-end harness behaviour on the smallest corpus entries."""

from __future__ import annotations

import pytest

from flab2bp.bench.corpus import URL_CORPUS, CorpusEntry, Tier, entries_for
from flab2bp.bench.report import matrix_report, render_markdown
from flab2bp.bench.runner import available_strategies, run_corpus


def test_corpus_is_twelve_entries_spanning_the_tiers() -> None:
    assert len(URL_CORPUS) == 12
    tiers = {e.tier for e in URL_CORPUS}
    assert tiers == {Tier.TRIVIAL, Tier.SMALL, Tier.MID, Tier.LARGE, Tier.STRESS}
    # Several entries must touch the LP-ambiguous multi-producer items.
    assert sum(1 for e in URL_CORPUS if e.multi_producer) >= 4


def test_every_corpus_url_is_v11_and_dsp() -> None:
    for entry in URL_CORPUS:
        assert "factoriolab.github.io/dsp/" in entry.url
        assert entry.url.endswith("&v=11")


def test_the_users_own_example_url_is_in_the_corpus() -> None:
    example = (
        "https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60"
        "&ibe=conveyor-belt-2"
        "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
        "&mps=proliferator-2-products&v=11"
    )
    assert any(e.url == example for e in URL_CORPUS)


def test_spine_strategy_is_discovered() -> None:
    names = {s.name for s in available_strategies(power=True)}
    assert "spine" in names


def test_missing_strategy_is_skipped_not_crashed() -> None:
    """Strategy B may not exist yet; discovery must degrade, not explode."""
    names = {s.name for s in available_strategies(power=True)}
    assert names <= {"spine", "freeform"}


@pytest.mark.parametrize("entry", entries_for(Tier.TRIVIAL), ids=lambda e: e.url_id)
def test_runs_end_to_end_on_trivial_entries(entry: CorpusEntry) -> None:
    results = run_corpus([entry], time_budget_s=0.5, candidates=1, powers=(True,))
    assert results
    for cell in results:
        assert cell.machines >= 1
        assert cell.area > 0
        # The validator must have actually run something.
        assert cell.checks_run > 0


def test_report_surfaces_skipped_checks_not_just_findings() -> None:
    """A build that skipped its throughput checks must not read as verified."""
    entry = entries_for(Tier.TRIVIAL)[0]
    results = run_corpus([entry], time_budget_s=0.5, candidates=1, powers=(True,))
    markdown = render_markdown(results)
    assert "skipped" in markdown.lower()


def test_matrix_report_has_a_cell_per_power_and_proliferation_combination() -> None:
    entry = entries_for(Tier.TRIVIAL)[0]
    results = run_corpus([entry], time_budget_s=0.5, candidates=2, powers=(True, False))
    matrix = matrix_report(results, "spine", "freeform")
    assert set(matrix.cells) == {
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    }


def test_matrix_reports_worst_case_and_fallback_rate_not_just_median() -> None:
    """Strategy B is predicted bimodal; an average would hide exactly that."""
    entry = entries_for(Tier.TRIVIAL)[0]
    results = run_corpus([entry], time_budget_s=0.5, candidates=1, powers=(True,))
    text = render_markdown(results, matrix=matrix_report(results, "spine", "freeform"))
    lowered = text.lower()
    assert "worst" in lowered
    assert "fallback" in lowered


def test_winning_candidate_is_reported_per_url_per_strategy() -> None:
    """If every strategy always picks the same candidate, that must be visible."""
    entry = entries_for(Tier.TRIVIAL)[0]
    results = run_corpus([entry], time_budget_s=0.5, candidates=2, powers=(True,))
    text = render_markdown(results)
    assert "candidate" in text.lower()
