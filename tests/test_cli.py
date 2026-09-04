"""Tests for :mod:`flab2bp.cli`'s report block.

Model: :mod:`tests.test_pipeline_cli_strategy`'s ``band_build`` fixture -- one
real, module-scoped build shared by every test here, so the whole module costs
one solve rather than one per test.
"""

from __future__ import annotations

import dataclasses

import pytest

from flab2bp import cli, pipeline
from flab2bp.rates.candidates import CandidatePolicy

#: The reported deuteron-fuel-rod URL (see ``tests/test_pipeline.py``'s
#: ``DEUTERON_URL`` for the fuller story). At the researched Mk.III belt tier
#: it belts hydrogen in at 40 items/s on exactly two entry lanes -- fast
#: (about 2 s at the default budget), so no budget override is needed here.
DEUTERON_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNzD0LwjAYBOB.k-GmJGKd3uWCuokVFLNaO2gthfqBOry"
    ".XSrGdHvu4K6TCOet6YQVnLWAG3weOWbP4O2.JybJOxSjqU--ZbKCnya.8pIc3n.hjeKr06GWYPr6KWtEHNHgDq7"
    "ALbgHG-UFvCIsNCwRSg0b07a9RKXOtTQPce4DLu01vA__&v=11"
)


@pytest.fixture(scope="module")
def deuteron_build() -> pipeline.Build:
    return pipeline.build(
        DEUTERON_URL,
        strategy="sequence-pair",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    )


def test_cli_reports_how_many_entry_lanes_an_item_needs(
    deuteron_build: pipeline.Build,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mk.III fits 40/s hydrogen on exactly two lanes of a 30/s belt.

    ``super-magnetic-ring`` is also belted in on two lanes here, for a reason
    unrelated to rate (two assembler strips, each wanting its own feed), so
    the report carries its own ``entry lanes:`` line too -- this test filters
    by looking for the hydrogen line specifically rather than asserting the
    whole report.
    """
    assert deuteron_build.report.ok
    cli._report(deuteron_build, verbose=False)
    report = capsys.readouterr().err
    assert "  entry lanes: hydrogen 2 (needs 2 at 30/s)" in report


def test_cli_always_reports_stack_one_without_a_url_suffix(
    deuteron_build: pipeline.Build,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unstacked bus is still an explicit reporting contract, but ``ist=1``
    needs no URL provenance suffix."""
    cli._report(deuteron_build, verbose=False)
    line = next(
        line for line in capsys.readouterr().err.splitlines() if line.strip().startswith("belts:")
    )
    assert line.endswith("; stack 1; 0 piler(s)")
    assert "URL ist=" not in line


def test_cli_names_the_stack_when_the_url_carries_one(
    deuteron_build: pipeline.Build,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`ist` is the player's own setting, so the report says it back with the
    URL field named -- a reader who did not expect stacked belts has to be able
    to find where the number came from."""
    stacked = dataclasses.replace(
        deuteron_build, spec=deuteron_build.spec.model_copy(update={"belt_stack": 2})
    )
    cli._report(stacked, verbose=False)
    line = next(
        line for line in capsys.readouterr().err.splitlines() if line.strip().startswith("belts:")
    )
    assert "stack 2 (URL ist=2)" in line
