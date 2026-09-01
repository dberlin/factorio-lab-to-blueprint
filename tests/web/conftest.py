"""One real build, shared.

The web layer's job is to report a :class:`~flab2bp.pipeline.Build` faithfully,
so testing it against a hand-rolled stand-in would test the stand-in.  One
genuine build is solved here and handed to every test that needs a real one --
the smallest spec in the suite, one candidate, one strategy, so the whole web
module costs a fraction of a second of CP-SAT rather than a minute.
"""

from __future__ import annotations

import pytest

from flab2bp import pipeline
from flab2bp.rates.candidates import CandidatePolicy

#: A small, known-buildable spec.
SMALL_URL = "https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11"


@pytest.fixture(scope="session")
def small_build() -> pipeline.Build:
    return pipeline.build(
        SMALL_URL,
        strategy="freeform",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=3.0,
    )
