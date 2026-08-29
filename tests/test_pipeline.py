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
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request
from flab2bp.lab.url import parse_url
from flab2bp.layout import finalize
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout, Placement
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.rates.candidates import _build_candidates_canonical
from flab2bp.spec import BuildSpecSet

#: Small, and known to lay out.  One candidate and one strategy so the test
#: costs a second of CP-SAT rather than a minute -- the sequence is the subject,
#: not the packing.
SMALL_URL = "https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11"

@pytest.mark.parametrize("pinned", [False, True])
def test_pipeline_canonicalizes_once_before_internal_consumers(
    monkeypatch: pytest.MonkeyPatch,
    pinned: bool,
) -> None:
    source_data = load_vendored()
    canonical_data = canonicalize_dataset(source_data)
    canonical_request = canonicalize_request(parse_url(SMALL_URL))
    assert hasattr(pipeline, "_pin_request_canonical")
    assert hasattr(pipeline, "_build_candidates_canonical")
    pinned_request = canonical_request
    dataset_calls = 0
    request_calls = 0
    seen: list[tuple[str, object, object]] = []

    def canonical_data_spy(data: object) -> object:
        nonlocal dataset_calls
        assert data is source_data
        dataset_calls += 1
        return canonical_data

    def canonical_request_spy(request: object) -> object:
        nonlocal request_calls
        request_calls += 1
        return canonical_request

    def pin_spy(request: object, data: object, selection: object) -> object:
        del selection
        assert request is canonical_request
        assert data is canonical_data
        seen.append(("pin", data, request))
        return pinned_request

    class ReachedCandidates(RuntimeError):
        pass

    def candidates_spy(data: object, request: object, **_kwargs: object) -> BuildSpecSet:
        assert data is canonical_data
        assert request is pinned_request
        seen.append(("candidates", data, request))
        raise ReachedCandidates

    monkeypatch.setattr(pipeline, "canonicalize_dataset", canonical_data_spy)
    monkeypatch.setattr(pipeline, "canonicalize_request", canonical_request_spy)
    monkeypatch.setattr(pipeline, "_pin_request_canonical", pin_spy)
    monkeypatch.setattr(pipeline, "_build_candidates_canonical", candidates_spy)
    if pinned:
        monkeypatch.setattr(pipeline, "flow_from_text", lambda *_args, **_kwargs: object())

    with pytest.raises(ReachedCandidates):
        pipeline.build(
            SMALL_URL,
            dataset=source_data,
            flow_text="flow" if pinned else None,
        )

    assert dataset_calls == 1
    assert request_calls == 1
    assert [entry[0] for entry in seen] == (
        ["pin", "candidates"] if pinned else ["candidates"]
    )


@pytest.mark.slow
def test_build_defaults_to_one_portable_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing the default or reparsing at either finalizer breaks this."""
    seen: list[BandPolicy] = []
    original_new_layout = pipeline._new_layout
    original_finalize = finalize.finalize_placement

    def new_layout_spy(
        strategy: pipeline.ExplicitStrategyName,
        *,
        power: bool,
        belt_vertical_construction: bool,
        sequence_islands: int = 1,
        band_policy: BandPolicy,
    ) -> FreeformLayout | SequencePairLayout:
        seen.append(band_policy)
        return original_new_layout(
            strategy,
            power=power,
            belt_vertical_construction=belt_vertical_construction,
            sequence_islands=sequence_islands,
            band_policy=band_policy,
        )

    def finalize_spy(
        placement: Placement,
        policy: BandPolicy,
    ) -> Placement:
        seen.append(policy)
        return original_finalize(placement, policy)

    monkeypatch.setattr(pipeline, "_new_layout", new_layout_spy)
    monkeypatch.setattr(finalize, "finalize_placement", finalize_spy)

    pipeline.build(
        SMALL_URL,
        strategy="freeform",
        candidates=1,
        time_budget_s=3.0,
    )

    assert len(seen) >= 3  # construction, internal finalization, pipeline defense
    assert seen[0] == BandPolicy("portable")
    assert all(policy is seen[0] for policy in seen)


@pytest.mark.slow
def test_every_pair_reports_started_and_then_how_it_ended() -> None:
    steps: list[pipeline.AttemptProgress] = []
    build = pipeline.build(
        SMALL_URL,
        strategy="freeform",
        band="160",
        candidates=2,
        time_budget_s=3.0,
        on_progress=steps.append,
    )

    # Two candidates, one strategy: two pairs, each reported when it starts and
    # when it either lays out or strictly refuses the requested band.
    assert [s.phase for s in steps[::2]] == ["started", "started"]
    assert all(s.phase in {"laid-out", "refused"} for s in steps[1::2])
    assert [s.index for s in steps] == [1, 1, 2, 2]
    assert {s.total for s in steps} == {2}

    # The settled pairs correspond exactly to the returned attempts/refusals.
    reported = {(s.candidate, s.strategy) for s in steps}
    assert len(reported) == 2
    assert {(s.candidate, s.strategy) for s in steps[1::2] if s.phase == "laid-out"} == {
        (a.candidate, a.strategy) for a in build.attempts
    }
    assert sum(s.phase == "refused" for s in steps[1::2]) == len(build.refused)

    # A settled pair carries either its layout verdict or its refusal reason.
    for step in steps:
        if step.phase == "started":
            assert step.area is None and step.ok is None and step.reason is None
        elif step.phase == "laid-out":
            assert step.area is not None and step.ok is not None and step.reason is None
        else:
            assert step.area is None and step.ok is None and step.reason is not None


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


def test_projection_refusal_preserves_structured_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = finalize.ProjectionFailure(
        check="geom.collide",
        buildings=(4, 9),
        detail="build colliders intersect",
        band=160,
    )
    second_failure = finalize.ProjectionFailure(
        check="game.power_too_close",
        buildings=(2, 7),
        detail="projected power envelopes intersect",
        band=200,
    )
    refusal = finalize.ProjectionRefusal((failure, second_failure))

    class RefusedLayout:
        def lay_out(self, _spec: object, *, time_budget_s: float) -> Placement:
            del time_budget_s
            return Placement(buildings=())

    monkeypatch.setattr(pipeline, "_new_layout", lambda *_args, **_kwargs: RefusedLayout())
    monkeypatch.setattr(
        finalize,
        "compact_open_boundary_belts",
        lambda placement, *_args, **_kwargs: placement,
    )
    monkeypatch.setattr(
        finalize,
        "finalize_placement",
        lambda _placement, _policy: (_ for _ in ()).throw(refusal),
    )
    steps: list[pipeline.AttemptProgress] = []

    with pytest.raises(NoValidLayout) as caught:
        pipeline.build(
            SMALL_URL,
            strategy="freeform",
            candidates=1,
            time_budget_s=0.5,
            on_progress=steps.append,
        )

    assert "band 160 geom.collide (4, 9): build colliders intersect" in caught.value.reason
    assert (
        "band 200 game.power_too_close (2, 7): projected power envelopes intersect"
        in caught.value.reason
    )
    assert caught.value.attempt_reasons == (caught.value.reason,)
    assert [
        (item.band, item.check, item.buildings, item.detail)
        for item in caught.value.projection_failures
    ] == [
        (item.band, item.check, item.buildings, item.detail)
        for item in (failure, second_failure)
    ]
    refused = steps[-1]
    assert refused.phase == "refused"
    assert refused.reason is not None
    assert [
        (item.band, item.check, item.buildings, item.detail)
        for item in refused.projection_failures
    ] == [
        (item.band, item.check, item.buildings, item.detail)
        for item in (failure, second_failure)
    ]


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
        spec_set = _build_candidates_canonical(*args, **kwargs)  # type: ignore[arg-type]
        sprayed = tuple(
            s for s in spec_set.candidates if any(g.is_proliferated for g in s.groups)
        )
        assert sprayed, "this URL produced no sprayed candidate to filter down to"
        return BuildSpecSet(candidates=sprayed)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "_build_candidates_canonical", only_sprayed)
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
            band="160",
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
