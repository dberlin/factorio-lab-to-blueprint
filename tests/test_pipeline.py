"""``pipeline.build`` says what it is doing while it does it.

Everything else about a build is observable from its result.  Which
(candidate, strategy) pair is currently in CP-SAT is not: it is the one fact a
caller with a progress bar needs and the one fact the return value cannot carry,
because by the time there is a return value the answer is "none of them".
"""

from __future__ import annotations

import pytest

from flab2bp import pipeline

#: Small, and known to lay out.  One candidate and one strategy so the test
#: costs a second of CP-SAT rather than a minute -- the sequence is the subject,
#: not the packing.
SMALL_URL = "https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11"


@pytest.mark.slow
def test_every_pair_reports_started_and_then_how_it_ended() -> None:
    steps: list[pipeline.AttemptProgress] = []
    build = pipeline.build(
        SMALL_URL,
        strategy="spine",
        candidates=2,
        time_budget_s=3.0,
        on_progress=steps.append,
    )

    # Two candidates, one strategy: two pairs, each reported twice.
    assert [s.phase for s in steps] == ["started", "laid-out", "started", "laid-out"]
    assert [s.index for s in steps] == [1, 1, 2, 2]
    assert {s.total for s in steps} == {2}

    # The pairs reported are the pairs that ran, not a guess at them.
    reported = {(s.candidate, s.strategy) for s in steps}
    assert reported == {(a.candidate, a.strategy) for a in build.attempts}

    # A settled pair carries its verdict; a starting one has not got one yet.
    for step in steps:
        if step.phase == "started":
            assert step.area is None and step.ok is None
        else:
            assert step.area is not None and step.ok is not None


@pytest.mark.slow
def test_the_index_counts_only_pairs_that_will_actually_run() -> None:
    """``total`` is a promise about how many reports are coming."""
    steps: list[pipeline.AttemptProgress] = []
    pipeline.build(
        SMALL_URL,
        strategy="best",
        candidates=1,
        time_budget_s=3.0,
        on_progress=steps.append,
    )
    started = [s for s in steps if s.phase == "started"]
    # One candidate x both strategies.
    assert len(started) == 2
    assert [s.index for s in started] == [1, 2]
    assert {s.total for s in started} == {2}
    assert {s.strategy for s in started} == {"spine", "freeform"}


def test_a_sink_that_raises_is_not_swallowed() -> None:
    """A progress sink is the caller's code, and a build must not eat its bugs.

    Wrapping this in a ``try/except`` would be the cheapest possible fallback:
    the build would finish, the bar would sit still, and nothing would say why.
    """

    class Boom(RuntimeError):
        pass

    def explode(_: pipeline.AttemptProgress) -> None:
        raise Boom("the caller's progress bar is broken")

    with pytest.raises(Boom):
        pipeline.build(
            SMALL_URL, strategy="spine", candidates=1, time_budget_s=0.5, on_progress=explode
        )
