"""``pipeline.build`` says what it is doing while it does it.

Everything else about a build is observable from its result.  Which
(candidate, strategy) pair is currently in CP-SAT is not: it is the one fact a
caller with a progress bar needs and the one fact the return value cannot carry,
because by the time there is a return value the answer is "none of them".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flab2bp import pipeline
from flab2bp.rates.candidates import build_candidates
from flab2bp.spec import BuildSpecSet

#: Small, and known to lay out.  One candidate and one strategy so the test
#: costs a second of CP-SAT rather than a minute -- the sequence is the subject,
#: not the packing.
SMALL_URL = "https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11"


@pytest.mark.slow
def test_every_pair_reports_started_and_then_how_it_ended() -> None:
    steps: list[pipeline.AttemptProgress] = []
    build = pipeline.build(
        SMALL_URL,
        strategy="freeform",
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
def test_best_reports_freeform_and_sequence_pairs() -> None:
    """``best`` resolves to both implemented strategies."""
    steps: list[pipeline.AttemptProgress] = []
    build = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidates=1,
        time_budget_s=3.0,
        on_progress=steps.append,
    )
    started = [s for s in steps if s.phase == "started"]
    # One candidate x the two production strategies.
    assert len(started) == 2
    assert [s.index for s in started] == [1, 2]
    assert {s.total for s in started} == {2}
    assert [s.strategy for s in started] == ["freeform", "sequence-pair"]
    valid = [attempt for attempt in build.attempts if attempt.ok]
    winner = min(valid, key=lambda attempt: attempt.area)
    assert (build.strategy, build.placement.area) == (winner.strategy, winner.area)


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
            SMALL_URL, strategy="freeform", candidates=1, time_budget_s=0.5, on_progress=explode
        )


@pytest.mark.slow
def test_no_proliferator_keeps_only_unsprayed_candidates() -> None:
    """`--no-proliferator` is read off the MODE, not off the label.

    The candidate labelled `no-proliferator` is that candidate by convention;
    `MachineGroup.proliferator_mode` is what actually decides whether a Spray
    Coater gets emitted. Assert the property that matters -- nothing sprayed,
    and so no coater in the blueprint -- rather than the name.
    """
    build = pipeline.build(
        SMALL_URL,
        strategy="freeform",
        candidates=3,
        time_budget_s=3.0,
        no_proliferator=True,
    )
    assert not any(g.is_proliferated for g in build.spec.groups), build.spec.label

    from flab2bp.dsp import catalog

    coaters = sum(
        1 for b in build.placement.buildings if b.item_id == catalog.SPRAY_COATER_ID
    )
    assert coaters == 0


@pytest.mark.slow
def test_no_proliferator_refuses_rather_than_quietly_spraying() -> None:
    """No unsprayed candidate must be a refusal, never a sprayed build.

    The whole project rule: a fallback hides a bug, a refusal names one. Here
    the fallback would be worse than usual because it is silent -- the caller
    asked for no coaters and would get coaters.
    """
    def only_sprayed(*args: object, **kwargs: object) -> BuildSpecSet:
        """Hand back only the candidates that DO spray, so none survives."""
        spec_set = build_candidates(*args, **kwargs)  # type: ignore[arg-type]
        sprayed = tuple(
            s for s in spec_set.candidates if any(g.is_proliferated for g in s.groups)
        )
        assert sprayed, "this URL produced no sprayed candidate to filter down to"
        return BuildSpecSet(candidates=sprayed)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "build_candidates", only_sprayed)
        with pytest.raises(ValueError, match="every candidate"):
            pipeline.build(
                SMALL_URL,
                strategy="freeform",
                candidates=3,
                time_budget_s=3.0,
                no_proliferator=True,
            )


#: The graphene spec and the FactorioLab export captured from it.  Paired: the
#: provenance check ties a flow to the URL it was generated from, so a fixture
#: is only usable with its own URL.
GRAPHENE_URL = (
    "https://factoriolab.github.io/dsp/list?o=graphene*60&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
)
GRAPHENE_FLOW = Path(__file__).parent / "fixtures" / "flow_graphene_real_capture.csv"


class TestFlowText:
    """``flow_text`` exists because the web front ends have no file to name.

    A paste and an upload are both text.  Writing that to a temporary path just
    so it could be read back would put a filesystem between the user's bytes and
    the parser, and would put its failure modes in the build's error surface.
    """

    @pytest.mark.slow
    def test_text_pins_exactly_as_a_path_does(self) -> None:
        from_text = pipeline.build(
            GRAPHENE_URL,
            strategy="freeform",
            candidates=1,
            time_budget_s=2.0,
            flow_text=GRAPHENE_FLOW.read_text(encoding="utf-8-sig"),
        )
        assert from_text.flow_pinned is True
        assert from_text.flow_findings == ()
        assert from_text.spec.label == "flow-pinned"

    def test_a_flow_from_a_different_url_is_refused_not_ignored(self) -> None:
        # The whole value of a pin is that it is FactorioLab's own selection.
        # Accepting an export from somewhere else would pin the build to a
        # decision nobody made for it.
        with pytest.raises(ValueError):
            pipeline.build(
                SMALL_URL,
                strategy="freeform",
                candidates=1,
                time_budget_s=0.5,
                flow_text=GRAPHENE_FLOW.read_text(encoding="utf-8-sig"),
            )

    def test_a_path_and_text_together_are_a_refusal(self) -> None:
        # Two flows are two different recipe selections. There is no right
        # guess, so there is no guess.
        with pytest.raises(ValueError, match="Pass one"):
            pipeline.build(
                GRAPHENE_URL,
                flow=GRAPHENE_FLOW,
                flow_text=GRAPHENE_FLOW.read_text(encoding="utf-8-sig"),
            )
