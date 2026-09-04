"""Tests for :mod:`flab2bp.cli`'s report block.

Model: :mod:`tests.test_pipeline_cli_strategy`'s ``band_build`` fixture -- one
real, module-scoped build shared by every test here, so the whole module costs
one solve rather than one per test.
"""

from __future__ import annotations

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
