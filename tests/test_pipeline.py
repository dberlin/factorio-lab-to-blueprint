"""``pipeline.build`` says what it is doing while it does it.

Everything else about a build is observable from its result.  Which
(candidate, strategy) pair is currently in CP-SAT is not: it is the one fact a
caller with a progress bar needs and the one fact the return value cannot carry,
because by the time there is a return value the answer is "none of them".
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import pytest

from flab2bp import pipeline
from flab2bp.dsp import catalog, codec
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.lab.url import parse_url
from flab2bp.layout import finalize, freeform, strategy_race, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import (
    ATOMIC_COMPLETION_GRACE_S,
    DEFAULT_SEARCH_WORKERS,
    AreaFrame,
    NoValidLayout,
    Placement,
    PlacementCompletion,
)
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.rates.candidates import (
    DEFAULT_CANDIDATE_POLICIES,
    CandidatePolicy,
    _build_candidates_canonical,
)
from flab2bp.spec import BuildSpec, BuildSpecSet

#: Small, and known to lay out.  One candidate and one strategy so the test
#: costs a second of CP-SAT rather than a minute -- the sequence is the subject,
#: not the packing.
SMALL_URL = "https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11"
DEADLINE_REGRESSION_URL = (
    "https://factoriolab.github.io/dsp/flow?"
    "z=eJzLt63SMjQwUMu3dQrWMgPTzlrGILpEywgi7qRlaGZgoKVlqJZvaw4ShLLDQBr"
    "B7MykVFsntdzcItvIOqc617pAtdyCYls3tTJbQ0MAjnsZAA__&v=11"
)


def _title_spec(
    outputs: dict[str, Fraction],
    *,
    label: str = "all-products",
) -> BuildSpec:
    return BuildSpec(groups=(), outputs=outputs, label=label)


def test_generated_title_under_the_game_limit_is_unchanged() -> None:
    spec = _title_spec({"space-warper": Fraction(1, 6)})

    assert pipeline._title(spec) == "space-warper 10/min (all products)"
    assert pipeline._generated_title(spec) == pipeline._title(spec)


def test_exact_81_character_generated_title_abbreviates_the_second_product_first() -> None:
    spec = _title_spec(
        {
            "quantum-chemical-plant": Fraction(20),
            "proliferator-mk3-component": Fraction(1),
        }
    )
    unbounded = (
        "quantum-chemical-plant 1200/min, "
        "proliferator-mk3-component 60/min (all products)"
    )

    assert len(unbounded) == 81
    assert pipeline._title(spec) == unbounded
    assert (
        pipeline._generated_title(spec)
        == "quantum-chemical-plant 1200/min, PMC 60/min (all products)"
    )


def test_first_product_is_abbreviated_only_after_the_second_is_not_enough() -> None:
    spec = _title_spec(
        {
            "very-long-first-product-identifier": Fraction(2),
            "very-long-second-product-identifier": Fraction(1),
            "third-product": Fraction(1, 2),
        },
        label="output-products",
    )

    assert (
        pipeline._generated_title(spec)
        == "VLFPI 120/min, VLSPI 60/min +1 more (output products)"
    )


def test_product_initials_are_uppercase_and_retain_numeric_hyphen_tokens() -> None:
    assert pipeline._product_initials("proliferator-3-component") == "P3C"


def test_generated_title_uses_one_ellipsis_when_initials_still_exceed_the_limit() -> None:
    spec = _title_spec(
        {
            "very-long-first-product-identifier": Fraction(int("9" * 40), 60),
            "very-long-second-product-identifier": Fraction(int("8" * 40), 60),
        }
    )

    title = pipeline._generated_title(spec)

    assert title == f"VLFPI {'9' * 40}/min, VLSPI 8…"
    assert pipeline._utf16_units(title) == pipeline.BLUEPRINT_SHORT_DESC_UTF16_LIMIT
    assert title.count("…") == 1


def test_utf16_ellipsis_truncation_never_splits_an_astral_character() -> None:
    title = pipeline._ellipsize_utf16("x" * 58 + "😀" + "tail")

    assert title == "x" * 58 + "…"
    assert pipeline._utf16_units(title) == 59
    title.encode("utf-16-le")


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
        assert _kwargs["candidate_policies"] == DEFAULT_CANDIDATE_POLICIES
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
    """Changing the default or reparsing during backend finalization breaks this."""
    seen: list[BandPolicy] = []
    expected_power: list[tuple[str, bool]] = []
    original_new_layout = pipeline._new_layout
    original_finalize = finalize.finalize_placement

    def new_layout_spy(
        strategy: pipeline.ExplicitStrategyName,
        *,
        belt_vertical_construction: bool,
        sequence_islands: int = 1,
        band_policy: BandPolicy,
        workers: int | None = None,
    ) -> FreeformLayout | SequencePairLayout:
        seen.append(band_policy)
        return original_new_layout(
            strategy,
            belt_vertical_construction=belt_vertical_construction,
            sequence_islands=sequence_islands,
            band_policy=band_policy,
            workers=workers,
        )

    def validate_spy(
        _placement: Placement,
        _spec: object,
        **kwargs: object,
    ) -> validate.Report:
        expected_power.append(("validate", kwargs["expect_power"] is True))
        return validate.Report(findings=())

    def finalize_spy(
        placement: Placement,
        policy: BandPolicy,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        seen.append(policy)
        return original_finalize(placement, policy, cancelled=cancelled)

    monkeypatch.setattr(pipeline, "_new_layout", new_layout_spy)
    monkeypatch.setattr(finalize, "finalize_placement", finalize_spy)
    monkeypatch.setattr(validate, "validate", validate_spy)

    pipeline.build(
        SMALL_URL,
        strategy="freeform",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=3.0,
    )

    assert len(seen) >= 3  # construction and backend finalization attempts
    assert seen[0] == BandPolicy("portable")
    assert all(policy is seen[0] for policy in seen)
    assert expected_power[-1] == ("validate", True)
    assert all(expect_power for _, expect_power in expected_power)


@pytest.fixture
def completed_layout(monkeypatch: pytest.MonkeyPatch) -> Placement:
    completed = Placement(
        buildings=(),
        frame=AreaFrame(1, 1, 4, (4,), False),
        completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
    )

    class CompletedLayout:
        def lay_out(self, _spec: object, *, time_budget_s: float) -> Placement:
            del time_budget_s
            return completed

    monkeypatch.setattr(
        pipeline,
        "_new_layout",
        lambda *_args, **_kwargs: CompletedLayout(),
    )
    monkeypatch.setattr(
        finalize,
        "compact_open_boundary_belts",
        lambda *_args, **_kwargs: pytest.fail("pipeline repeated backend compaction"),
    )
    monkeypatch.setattr(
        finalize,
        "finalize_placement",
        lambda *_args, **_kwargs: pytest.fail("pipeline repeated backend finalization"),
    )
    monkeypatch.setattr(
        validate,
        "validate",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    return completed


def test_completed_backend_output_skips_duplicate_completion(
    completed_layout: Placement,
) -> None:
    result = pipeline.build(
        SMALL_URL,
        strategy="sequence-pair",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=0.5,
    )

    assert result.placement.completion is completed_layout.completion


def test_explicit_over_cap_pipeline_name_is_unchanged(
    completed_layout: Placement,
) -> None:
    explicit_name = "explicit-" + "x" * 53
    assert len(explicit_name) == 62

    result = pipeline.build(
        SMALL_URL,
        strategy="sequence-pair",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=0.5,
        name=explicit_name,
    )

    assert result.placement.completion is completed_layout.completion
    assert result.placement.short_desc == explicit_name
    assert codec.decode(result.blueprint).header.short_desc == explicit_name


def test_blueprint_encoding_failure_does_not_abort_later_strategy(
    completed_layout: Placement,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encode = codec.encode
    calls = 0

    def fail_first(placement: Placement) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("invalid splitter port anchor")
        return encode(placement)

    monkeypatch.setattr(codec, "encode", fail_first)
    result = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=0.5,
    )

    assert result.strategy == "sequence-pair"
    assert result.placement.completion is completed_layout.completion
    assert len(result.attempts) == 1
    assert len(result.refused) == 1
    assert result.refused[0].strategy == "freeform"
    assert result.refused[0].reason == (
        "blueprint encoding failed: invalid splitter port anchor"
    )

@pytest.mark.slow
def test_every_pair_reports_started_and_then_how_it_ended() -> None:
    steps: list[pipeline.AttemptProgress] = []
    build = pipeline.build(
        SMALL_URL,
        strategy="freeform",
        band="160",
        candidate_policies=(
            CandidatePolicy.ALL_PRODUCTS,
            CandidatePolicy.NO_PROLIFERATOR,
        ),
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
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
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
            SMALL_URL,
            strategy="freeform",
            candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
            time_budget_s=0.5,
            on_progress=explode,
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
        lambda _placement, _policy, **_kwargs: (_ for _ in ()).throw(refusal),
    )
    steps: list[pipeline.AttemptProgress] = []

    with pytest.raises(NoValidLayout) as caught:
        pipeline.build(
            SMALL_URL,
            strategy="freeform",
            candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
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


@pytest.mark.slow
def test_graphene_output_products_sequence_pair_reports_its_continuation_batches() -> None:
    """A cell that certifies inside its stage schedule appends no restart batch.

    This test was planned as ``>= 1.0``: before Phase C the fast-path stage cap
    (``_search_stage_cap`` returns 2 for this spec -- 6 machines, under
    ``_TOPOLOGY_BEAM_MIN_STRIPS``, two spray lanes) ended the search with clock
    left and the cell refused with "no scheduled stage produced an exact
    layout".  Master 22bf910's recipe-pricing change fixed the cell before the
    continuation landed, so the spec now certifies an exact incumbent inside its
    scheduled stages -- measured 2026-09-02: ``termination='stage-limit'``,
    ``anneal_stages=4``, ``area=420``, 0.45 s of placement.

    ``lay_out`` still passes ``feasibility_continuation=True``, so the branch is
    reached at the stage limit and declines to append because an exact incumbent
    already exists.  What this pins is that the cell stays CLEAN and that the
    stat reaches ``PlacementStats`` at all -- the subscript is the key-presence
    assertion.  It deliberately does NOT pin the count: whether this cell needs a
    batch is a property of the recipe pricing, not of the continuation, and the
    appending path is pinned by the unit tests in
    ``tests/layout/test_sequence_solver.py``.
    """
    from flab2bp.bench.corpus import URL_CORPUS
    from flab2bp.rates.candidates import build_candidates

    entry = next(candidate for candidate in URL_CORPUS if candidate.url_id == "graphene")
    built = build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=DEFAULT_CANDIDATE_POLICIES,
    )
    spec = next(
        candidate for candidate in built.candidates if candidate.label == "output-products"
    )
    placement = SequencePairLayout(band_policy=BandPolicy("portable")).lay_out(
        spec, time_budget_s=30.0
    )
    assert placement.stats["area"] > 0.0
    assert placement.stats["feasibility_restart_batches"] >= 0.0


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
            candidate_policies=(CandidatePolicy.OUTPUT_PRODUCTS,),
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
                candidate_policies=(CandidatePolicy.OUTPUT_PRODUCTS,),
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

@pytest.mark.slow
def test_all_products_sequence_pair_honours_the_exact_layout_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Counts real firings of freeform._PreparationDeadline -- the cancellation
    # 0d2a69b added inside exact sequence preparation (_prepare_routing_problem,
    # _power_plan, _prospective_static_failure, _place_coaters). A subclass, not
    # a bare stand-in: sequence_solver.py caught the original class by its own
    # `from ... import _PreparationDeadline` binding at import time, so patching
    # only `freeform._PreparationDeadline` -- where every `raise
    # _PreparationDeadline` in that module resolves the name -- still lands in
    # that `except` via isinstance, with no need to touch sequence_solver's copy.
    preparation_deadline_fires = 0

    class _CountingPreparationDeadline(freeform._PreparationDeadline):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            nonlocal preparation_deadline_fires
            preparation_deadline_fires += 1

    monkeypatch.setattr(freeform, "_PreparationDeadline", _CountingPreparationDeadline)

    started = time.monotonic()

    # Measured 2026-09-01: since commit 8161392 sped up preparation, this build
    # now *succeeds* at time_budget_s=10.0 (~10.3s wall) instead of exhausting
    # the deadline. 1.5s is small enough that exact preparation is still
    # reliably cancelled mid-flight (verified: NoValidLayout, 3/3 runs).
    #
    # THE CEILING IS 2.0s, MEASURED: at 2.0 the solver sometimes SUCCEEDS on
    # this URL, so the budget has to stay strictly below it or the test is
    # flaky rather than wrong. The mechanism is deliberately a real cell that
    # exhausts inside exact preparation rather than a mechanised clock,
    # because what is under test is that the preparation path itself honours
    # the deadline -- a faked clock would prove that the fake fired.
    #
    # So this budget is a moving target by design: the next preparation
    # speedup that makes 1.5s enough to finish will fail here with
    # `DID NOT RAISE NoValidLayout`. That failure is the test working. Lower
    # the budget until the refusal is reliable again (and re-measure the
    # ceiling), rather than relaxing the assertion.
    budget = 1.5
    with pytest.raises(NoValidLayout, match="deadline exhausted"):
        pipeline.build(
            DEADLINE_REGRESSION_URL,
            strategy="sequence-pair",
            candidate_policies=(CandidatePolicy.ALL_PRODUCTS,),
            time_budget_s=budget,
        )

    assert time.monotonic() - started < budget + 2.5
    # Without this, a deadline hit anywhere else (e.g. before the search loop
    # ever reached a candidate) would also raise "deadline exhausted" and pass
    # -- this is what actually proves the refusal happened during exact
    # preparation, the code path 0d2a69b guarded.
    assert preparation_deadline_fires > 0


@pytest.mark.slow
def test_every_attempt_reports_its_wall_and_its_overshoot() -> None:
    built = pipeline.build(
        SMALL_URL,
        strategy="freeform",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=5.0,
    )

    assert built.attempts
    for attempt in built.attempts:
        stats = attempt.placement.stats
        assert stats["attempt_wall_s"] > 0.0
        assert stats["wall_overshoot_s"] == max(
            0.0, stats["attempt_wall_s"] - 5.0 - ATOMIC_COMPLETION_GRACE_S
        )


def _stub_needs_finalization(
    monkeypatch: pytest.MonkeyPatch,
    *,
    advance_s: float,
    capture: dict[str, object] | None = None,
) -> list[float]:
    """Rig one freeform attempt whose placement is NOT already
    ``COMPACTED_AND_FINALIZED``, so `pipeline.build` takes the
    `finalize.finalize_placement` branch under test, on a driven clock rather
    than the real one.

    Returns the mutable one-element clock box: from the moment this returns,
    `time.monotonic()` inside `pipeline.build` reads `now[0]`, so a test can
    move it *after* `build` returns to probe a captured predicate against a
    deadline it already knows.
    """
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    class _NeedsFinalization:
        def lay_out(self, _spec: object, *, time_budget_s: float) -> Placement:
            del time_budget_s
            now[0] += advance_s
            return Placement(buildings=(), completion=None, frame=None)

    monkeypatch.setattr(pipeline, "_new_layout", lambda *_a, **_kw: _NeedsFinalization())
    monkeypatch.setattr(
        finalize, "compact_open_boundary_belts", lambda placement, *_a, **_kw: placement
    )

    def _finalize(
        placement: Placement,
        _policy: object,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        if capture is not None:
            capture["cancelled"] = cancelled
        return dataclasses.replace(placement, frame=AreaFrame(1, 1, 4, (4,), False))

    monkeypatch.setattr(finalize, "finalize_placement", _finalize)
    monkeypatch.setattr(validate, "validate", lambda *_a, **_kw: validate.Report(findings=()))
    return now


def test_wall_overshoot_is_clamped_at_zero_under_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_needs_finalization(monkeypatch, advance_s=2.0)

    built = pipeline.build(
        SMALL_URL,
        strategy="freeform",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=5.0,
    )

    stats = built.attempts[0].placement.stats
    # 2.0s wall is well under budget(5.0) + grace(5.0) = 10.0s -- clamped, not
    # negative.
    assert stats["attempt_wall_s"] == pytest.approx(2.0)
    assert stats["wall_overshoot_s"] == 0.0


def test_wall_overshoot_reports_the_excess_past_budget_and_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_needs_finalization(monkeypatch, advance_s=20.0)

    built = pipeline.build(
        SMALL_URL,
        strategy="freeform",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=5.0,
    )

    stats = built.attempts[0].placement.stats
    assert stats["attempt_wall_s"] == pytest.approx(20.0)
    # 20.0 - budget(5.0) - ATOMIC_COMPLETION_GRACE_S(5.0) == 10.0
    assert stats["wall_overshoot_s"] == pytest.approx(20.0 - 5.0 - ATOMIC_COMPLETION_GRACE_S)


def test_finalize_placement_receives_a_cancelled_predicate_over_the_attempt_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, object] = {}
    now = _stub_needs_finalization(monkeypatch, advance_s=0.0, capture=capture)

    pipeline.build(
        SMALL_URL,
        strategy="freeform",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=3.0,
    )

    cancelled = capture["cancelled"]
    assert callable(cancelled)
    # attempt_started was 1000.0 (advance_s=0.0 never moved the clock before
    # finalize_placement captured this predicate); the deadline it closes over
    # is attempt_started + time_budget_s + ATOMIC_COMPLETION_GRACE_S.
    deadline = 1000.0 + 3.0 + ATOMIC_COMPLETION_GRACE_S
    now[0] = deadline - 0.001
    assert cancelled() is False
    now[0] = deadline
    assert cancelled() is True


def test_a_finalization_cancelled_by_the_attempt_deadline_is_reported_as_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`finalize_placement` now sees `cancelled`, so it can raise
    `finalize.ProjectionCancelled` -- a bare Exception, not a ProjectionRefusal
    subclass. Every other call site that hands `finalize_placement` a
    `cancelled` predicate (sequence_solver.py, freeform.py) catches this
    alongside ProjectionRefusal; pipeline.build must too, or a single
    attempt's cancellation crashes the whole build rather than refusing that
    attempt -- "a number the gate can fail on beats a number nobody produced"
    kept for real, not just reported.
    """
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    class _NeedsFinalization:
        def lay_out(self, _spec: object, *, time_budget_s: float) -> Placement:
            del time_budget_s
            return Placement(buildings=(), completion=None, frame=None)

    monkeypatch.setattr(pipeline, "_new_layout", lambda *_a, **_kw: _NeedsFinalization())
    monkeypatch.setattr(
        finalize, "compact_open_boundary_belts", lambda placement, *_a, **_kw: placement
    )

    def _always_cancelled(
        _placement: Placement,
        _policy: object,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        assert cancelled is not None
        # attempt_started(1000.0) + budget(5.0) + grace(5.0) == 1010.0 -- push
        # the driven clock past it so `attempt_expired()` reads True, exactly
        # what a real deadline firing during finalization looks like (and what
        # the hardening check inside the except clause requires before it will
        # convert this into a refusal at all).
        now[0] = 1010.0
        raise finalize.ProjectionCancelled

    monkeypatch.setattr(finalize, "finalize_placement", _always_cancelled)

    steps: list[pipeline.AttemptProgress] = []
    with pytest.raises(NoValidLayout) as exc_info:
        pipeline.build(
            SMALL_URL,
            strategy="freeform",
            candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
            time_budget_s=5.0,
            on_progress=steps.append,
        )

    assert len(exc_info.value.attempt_failures) == 1
    failure = exc_info.value.attempt_failures[0]
    assert failure.strategy == "freeform"
    assert "deadline" in failure.reason

    refused_steps = [s for s in steps if s.phase == "refused"]
    assert len(refused_steps) == 1
    assert refused_steps[0].reason == failure.reason


def test_the_deadline_refusal_reason_pins_wall_budget_and_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the exact refusal text under a driven clock: the measured wall
    (not just the static budget and grace) must be in it, formatted to one
    decimal, so a reader sees how far past the deadline finalization actually
    ran rather than just the two numbers that define the deadline.
    """
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    class _NeedsFinalization:
        def lay_out(self, _spec: object, *, time_budget_s: float) -> Placement:
            del time_budget_s
            return Placement(buildings=(), completion=None, frame=None)

    monkeypatch.setattr(pipeline, "_new_layout", lambda *_a, **_kw: _NeedsFinalization())
    monkeypatch.setattr(
        finalize, "compact_open_boundary_belts", lambda placement, *_a, **_kw: placement
    )

    def _cancel_past_deadline(
        _placement: Placement,
        _policy: object,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        del cancelled
        # attempt_started(1000.0) + budget(3.0) + grace(5.0) == 1008.0 --
        # land 0.4s past it, at a value whose fractional part exercises the
        # ":.1f" formatting rather than landing on a round number by luck.
        now[0] = 1008.4
        raise finalize.ProjectionCancelled

    monkeypatch.setattr(finalize, "finalize_placement", _cancel_past_deadline)

    with pytest.raises(NoValidLayout) as exc_info:
        pipeline.build(
            SMALL_URL,
            strategy="freeform",
            candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
            time_budget_s=3.0,
        )

    reason = exc_info.value.attempt_failures[0].reason
    assert reason == (
        "attempt deadline exhausted during finalization after 8.4s "
        "(budget 3s + grace 5s)"
    )


def test_a_cancellation_before_the_deadline_is_not_relabelled_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`attempt_expired` is the only `cancelled` predicate this call site ever
    hands `finalize_placement`, so a `ProjectionCancelled` raised while that
    predicate still reads False cannot be an attempt-deadline cancellation --
    it can only be some future, unrelated cancel source. Relabelling it
    "deadline exhausted" would be a lie about why the attempt was refused;
    this call site must re-raise instead of guessing.
    """
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)

    class _NeedsFinalization:
        def lay_out(self, _spec: object, *, time_budget_s: float) -> Placement:
            del time_budget_s
            return Placement(buildings=(), completion=None, frame=None)

    monkeypatch.setattr(pipeline, "_new_layout", lambda *_a, **_kw: _NeedsFinalization())
    monkeypatch.setattr(
        finalize, "compact_open_boundary_belts", lambda placement, *_a, **_kw: placement
    )

    def _cancel_before_deadline(
        _placement: Placement,
        _policy: object,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        del cancelled
        # The clock never moves: attempt_started(1000.0) + budget(5.0) +
        # grace(5.0) == 1010.0, and `time.monotonic()` stays pinned at
        # 1000.0 -- `attempt_expired()` reads False throughout.
        raise finalize.ProjectionCancelled

    monkeypatch.setattr(finalize, "finalize_placement", _cancel_before_deadline)

    with pytest.raises(finalize.ProjectionCancelled):
        pipeline.build(
            SMALL_URL,
            strategy="freeform",
            candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
            time_budget_s=5.0,
        )


DEUTERON_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNzD0LwjAYBOB.k-GmJGKd3uWCuokVFLNaO2gthfqBOry"
    ".XSrGdHvu4K6TCOet6YQVnLWAG3weOWbP4O2.JybJOxSjqU--ZbKCnya.8pIc3n.hjeKr06GWYPr6KWtEHNHgDq7"
    "ALbgHG-UFvCIsNCwRSg0b07a9RKXOtTQPce4DLu01vA__&v=11"
)


def _with_belt(
    monkeypatch: pytest.MonkeyPatch,
    belt_id: str,
    *,
    researched: set[str] | None = None,
    stack: Fraction | None = None,
) -> None:
    """Rewrite the URL's belt, and optionally its technology set and its `ist`.

    Patching the request rather than the URL string keeps the corpus URLs
    verbatim -- no corpus URL carries `ist>1`, and inventing one by hand-editing
    an encoded payload would be a fixture nobody could check against
    FactorioLab.
    """
    original = pipeline.parse_url  # type: ignore[attr-defined]

    def patched(url: str, **kwargs: object):  # type: ignore[no-untyped-def]
        replacements: dict[str, object] = {"belt_id": belt_id}
        if researched is not None:
            replacements["researched_technology_ids"] = set(researched)
        if stack is not None:
            replacements["stack"] = stack
        return dataclasses.replace(original(url, **kwargs), **replacements)  # type: ignore[arg-type]

    monkeypatch.setattr(pipeline, "parse_url", patched)


@pytest.mark.slow
def test_a_mk2_url_whose_lanes_need_mk3_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reported failure: hydrogen lanes at 14-20/s on a 12/s belt.  With
    Mk.III researched, those runs are raised and the build validates."""
    _with_belt(monkeypatch, "conveyor-belt-2")
    # One policy keeps this test under a single 45 s budget and pytest-timeout's
    # 120 s backstop; the tier logic under test is policy-independent.
    # NO_PROLIFERATOR is picked (not OUTPUT_PRODUCTS) because it is the only
    # policy that lays this candidate out at all within budget here.
    build = pipeline.build(
        DEUTERON_URL,
        strategy="sequence-pair",
        time_budget_s=45.0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    )
    assert build.report.ok
    assert build.spec.belt_item_id == "conveyor-belt-2"
    tiers = {b.item_id for b in build.placement.buildings if catalog.is_belt(b.item_id)}
    assert 2003 in tiers, "some run needed Mk.III"
    # The floor-keeping property (a run within the floor keeps it) is a
    # per-run invariant covered by tests/layout/test_belt_tiers.py; here we
    # only need to know retiering never introduces a belt outside the floor
    # and its one researched upgrade.
    assert tiers <= {2002, 2003}, "no belt outside the floor and its upgrade"
    assert build.placement.stats["belt_runs_upgraded"] >= 1


@pytest.mark.slow
def test_without_planetary_logistics_hydrogen_arrives_on_four_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mk.II is the ceiling (12/s) and hydrogen enters at 40/s, so the cap
    shortens the collider strips until four entry lanes carry it.  Before the
    multiple-belts work this URL was refused with ``flow.belt_capacity``.

    Budget: 45 s on a sequence-pair build at ~30 s plus preparation keeps this
    under pytest-timeout's 120 s backstop even on a loaded box.
    """
    _with_belt(monkeypatch, "conveyor-belt-2", researched={
        "basic-logistics-system", "improved-logistics-system",
        "high-efficiency-logistics-system",
    })
    build = pipeline.build(DEUTERON_URL, strategy="sequence-pair", time_budget_s=45.0,
                           candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,))
    assert build.report.ok
    findings = build.report.by_check("flow.external_entry_points")
    # super-magnetic-ring is also belted in on two lanes (two assembler strips,
    # each wanting its own feed); only hydrogen is this test's subject.
    (finding,) = [f for f in findings if f.detail["item"] == "hydrogen"]
    assert finding.detail["entry_lanes"] == finding.detail["lanes_needed"] == 4
    # The family machine cap binds at the strip partition seam, so capacity
    # comes from lane splitting rather than a belt upgrade: no strip ever
    # needs a tier the floor belt (conveyor-belt-2, item 2002) doesn't cover.
    tiers = {b.item_id for b in build.placement.buildings if catalog.is_belt(b.item_id)}
    assert tiers == {2002}, "no Mk.III belt: capacity comes from lane splitting, not tier"


def test_at_mk3_hydrogen_above_the_ceiling_arrives_on_two_lanes() -> None:
    """Mk.III already fits 40/s hydrogen on two lanes through the ordinary
    ``strip_len`` heuristic (10 colliders split 5 + 5, 20/s each, and the cap
    of 7 is inert); this pins that the new ``lanes_needed`` detail agrees with
    the lanes actually built.  Fast (about 2 s at the default budget): not
    slow, no budget bump."""
    build = pipeline.build(DEUTERON_URL, strategy="sequence-pair",
                           candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,))
    assert build.report.ok
    findings = build.report.by_check("flow.external_entry_points")
    (finding,) = [f for f in findings if f.detail["item"] == "hydrogen"]
    assert finding.detail["entry_lanes"] == finding.detail["lanes_needed"] == 2


# --- Task 14: `workers`, opt-in racing, and the relaxed islands guard ---------

#: A budget the stubbed race never actually spends.  Named so the refusal an
#: arm reports and the budget the build was asked for cannot drift apart.
STUB_RACE_BUDGET_S = 4.0


def _finished(width: int, height: int) -> Placement:
    """A finished placement, cheap enough to stand in for a raced arm's result.

    Same shape the ``completed_layout`` fixture uses: no buildings, a frame, and
    ``COMPACTED_AND_FINALIZED`` so the pipeline's completion branch is skipped.
    Two distinct objects are needed per race, because ``dataclasses.replace``
    shares the ``stats`` dict and one shared dict cannot carry two walls.
    """
    return Placement(
        buildings=(),
        frame=AreaFrame(width, height, 4, (4,), False),
        completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
    )


def _install_stub_race(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: tuple[strategy_race._StrategyRaceOutcome, ...],
    calls: list[dict[str, object]],
    on_call: Callable[[], None] | None = None,
) -> None:
    """Replace the race with a recorder, so a raced build spawns nothing.

    ``on_call`` runs before the outcomes are handed back, which is where a
    driven clock spends the race's wall: the pipeline must see time pass
    between ``race_started`` and the settlement, or a grace cannot be tested.
    """

    def record(
        spec: BuildSpec, **kwargs: object
    ) -> tuple[strategy_race._StrategyRaceOutcome, ...]:
        calls.append({"spec": spec, **kwargs})
        if on_call is not None:
            on_call()
        return outcomes

    monkeypatch.setattr(strategy_race, "run_strategy_race", record)
    monkeypatch.setattr(
        validate,
        "validate",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )


def _one_win_one_refusal() -> tuple[strategy_race._StrategyRaceOutcome, ...]:
    return (
        strategy_race._StrategyRaceOutcome(
            "freeform",
            "completed",
            placement=_finished(2, 3),
        ),
        strategy_race._StrategyRaceOutcome.refused(
            "sequence-pair",
            "no arrangement fit the band",
            "no-proliferator",
            STUB_RACE_BUDGET_S,
        ),
    )


def test_islands_are_legal_with_best_and_still_illegal_with_freeform() -> None:
    # Islands now live INSIDE the sequence-pair racer, so `best` may ask for
    # them.  The guard fires before any URL work, so a bogus URL proves which
    # rejection we got: `freeform` must fail on the guard's own message, and
    # `best` must get past it and fail on the URL instead.
    with pytest.raises(ValueError, match="sequence islands"):
        pipeline.build("not-a-url", strategy="freeform", sequence_islands=2)

    with pytest.raises(Exception) as caught:
        pipeline.build("not-a-url", strategy="best", sequence_islands=2)

    assert "sequence islands" not in str(caught.value)


@pytest.mark.slow
def test_best_is_serial_until_a_caller_opts_into_racing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default must not race, so every existing `best` caller is unchanged."""
    races = 0

    def counting(*_args: object, **_kwargs: object) -> tuple[object, ...]:
        nonlocal races
        races += 1
        raise AssertionError("race=False must never reach run_strategy_race")

    # The pipeline reaches `run_strategy_race` through this module object, so
    # patching the attribute here is what a raced build would pick up.
    monkeypatch.setattr(strategy_race, "run_strategy_race", counting)

    build = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=3.0,
    )

    assert races == 0
    assert {attempt.strategy for attempt in build.attempts} | {
        failure.strategy for failure in build.refused
    } == {"freeform", "sequence-pair"}


def test_a_raced_build_reports_one_attempt_or_failure_per_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each outcome becomes exactly one Attempt or one LayoutAttemptFailure."""
    calls: list[dict[str, object]] = []
    _install_stub_race(monkeypatch, _one_win_one_refusal(), calls)
    steps: list[pipeline.AttemptProgress] = []

    built = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=STUB_RACE_BUDGET_S,
        race=True,
        on_progress=steps.append,
    )

    assert len(calls) == 1
    assert [attempt.strategy for attempt in built.attempts] == ["freeform"]
    assert [failure.strategy for failure in built.refused] == ["sequence-pair"]
    assert built.refused[0].reason == "no arrangement fit the band"
    assert built.strategy == "freeform"
    assert built.placement.area == 6
    # One candidate x two strategies, counted and settled exactly as serially.
    assert [step.index for step in steps] == [1, 2, 1, 2]
    assert {step.total for step in steps} == {2}
    assert [step.phase for step in steps] == ["started", "started", "laid-out", "refused"]
    assert [step.strategy for step in steps] == [
        "freeform",
        "sequence-pair",
        "freeform",
        "sequence-pair",
    ]


def test_both_arms_are_announced_before_the_race_rather_than_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec 5.4: ``started`` fires for both pairs BEFORE the race.

    Announcing afterwards would leave a progress bar silent for a whole budget
    and then jump by two, which is the one thing ``AttemptProgress`` exists to
    prevent -- and it would make the field's own docstring ("``started`` fires
    before the solve") false for a raced build.
    """
    steps: list[pipeline.AttemptProgress] = []
    announced_when_the_race_began: list[int] = []
    outcomes = _one_win_one_refusal()

    def record(
        _spec: BuildSpec, **_kwargs: object
    ) -> tuple[strategy_race._StrategyRaceOutcome, ...]:
        announced_when_the_race_began.append(len(steps))
        return outcomes

    monkeypatch.setattr(strategy_race, "run_strategy_race", record)
    monkeypatch.setattr(
        validate,
        "validate",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )

    pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=STUB_RACE_BUDGET_S,
        race=True,
        on_progress=steps.append,
    )

    assert announced_when_the_race_began == [2]
    assert [step.phase for step in steps[:2]] == ["started", "started"]


def test_racing_forwards_every_knob_the_race_owns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``workers`` is forwarded WHOLE: the race, not the pipeline, splits it."""
    calls: list[dict[str, object]] = []
    _install_stub_race(monkeypatch, _one_win_one_refusal(), calls)
    rules = belt_rules_for_url(SMALL_URL, canonicalize_dataset(load_vendored()))

    pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=STUB_RACE_BUDGET_S,
        race=True,
        share=False,
        workers=9,
        sequence_islands=2,
    )

    assert len(calls) == 1
    call = dict(calls[0])
    assert call.pop("spec") is not None
    assert call == {
        "time_budget_s": STUB_RACE_BUDGET_S,
        "band_policy": BandPolicy("portable"),
        "belt_vertical_construction": rules.vertical_construction,
        "max_belt_z": rules.max_z,
        "workers": 9,
        "sequence_islands": 2,
        "share": False,
    }
    # Pre-splitting here would split twice: `run_strategy_race` calls
    # `race_worker_split` itself, and (6, 3) is what 9 becomes inside it.
    assert strategy_race.race_worker_split(9) == (6, 3)


def test_an_explicit_strategy_never_races_even_when_asked_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Racing is a ``best`` mechanism: there is no second arm to race against."""
    calls: list[dict[str, object]] = []
    _install_stub_race(monkeypatch, _one_win_one_refusal(), calls)
    seen: list[int | None] = []

    class _Completed:
        def lay_out(self, _spec: object, *, time_budget_s: float) -> Placement:
            del time_budget_s
            return _finished(2, 2)

    def spy(
        _strategy: pipeline.ExplicitStrategyName,
        *,
        belt_vertical_construction: bool,
        sequence_islands: int = 1,
        band_policy: BandPolicy,
        workers: int | None = None,
    ) -> _Completed:
        del belt_vertical_construction, sequence_islands, band_policy
        seen.append(workers)
        return _Completed()

    monkeypatch.setattr(pipeline, "_new_layout", spy)

    built = pipeline.build(
        SMALL_URL,
        strategy="freeform",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=STUB_RACE_BUDGET_S,
        race=True,
        workers=7,
    )

    assert calls == []
    assert seen == [7]
    assert [attempt.strategy for attempt in built.attempts] == ["freeform"]


def test_racing_rejects_sequence_islands_outside_the_serial_range_before_submitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raced build must refuse an out-of-range island count before any child

    is submitted, exactly as the serial path already does at construction.
    ``run_strategy_race`` (real, not stubbed here) is what must raise: this
    test stubs only ``_pool_submit``, the actual submission call, to prove the
    ``ValueError`` fires before it -- a race that submitted first would report
    two crashed arms instead of raising.
    """

    def _never_submitted(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("no race may be submitted for an out-of-range island count")

    monkeypatch.setattr(strategy_race, "_pool_submit", _never_submitted)

    with pytest.raises(ValueError, match="islands must be an integer from 1 to"):
        pipeline.build(
            SMALL_URL,
            strategy="best",
            candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
            time_budget_s=STUB_RACE_BUDGET_S,
            race=True,
            sequence_islands=99,
        )


def test_the_serial_path_settles_each_pair_before_starting_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serial `best` interleaves solve and settlement, exactly as it always did.

    Resolving both strategies up front and settling them afterwards would look
    identical in the result, and would still be wrong: an attempt's
    ``attempt_deadline`` is its own solve start plus one budget and the grace,
    so the first pair's finalization would begin a whole budget late and refuse
    a placement that is fine.
    """
    steps: list[pipeline.AttemptProgress] = []

    class _Completed:
        def lay_out(self, _spec: object, *, time_budget_s: float) -> Placement:
            del time_budget_s
            return _finished(2, 2)

    monkeypatch.setattr(pipeline, "_new_layout", lambda *_a, **_k: _Completed())
    monkeypatch.setattr(
        validate,
        "validate",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )

    pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=STUB_RACE_BUDGET_S,
        on_progress=steps.append,
    )

    assert [step.phase for step in steps] == [
        "started",
        "laid-out",
        "started",
        "laid-out",
    ]
    assert [step.index for step in steps] == [1, 1, 2, 2]


def test_workers_reaches_the_freeform_layout_it_configures() -> None:
    """The knob exists so a racer's share is a number, not all 128 cores."""
    freeform_layout = pipeline._new_layout(
        "freeform",
        belt_vertical_construction=True,
        band_policy=BandPolicy("portable"),
        workers=7,
    )
    default_layout = pipeline._new_layout(
        "freeform",
        belt_vertical_construction=True,
        band_policy=BandPolicy("portable"),
    )

    assert isinstance(freeform_layout, FreeformLayout)
    assert isinstance(default_layout, FreeformLayout)
    assert freeform_layout.workers == 7
    # `None` is unchanged behaviour: freeform's own default, all cores.
    assert default_layout.workers == DEFAULT_SEARCH_WORKERS


def test_a_terminated_or_crashed_arm_is_a_failure_and_never_an_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A killed arm has no placement, so counting it as an Attempt is a lie."""
    calls: list[dict[str, object]] = []
    _install_stub_race(
        monkeypatch,
        (
            strategy_race._StrategyRaceOutcome(
                "freeform",
                "terminated",
                refusal_reason="freeform overran the 4s budget and was terminated",
            ),
            strategy_race._StrategyRaceOutcome(
                "sequence-pair",
                "crashed",
                refusal_reason="sequence-pair strategy process failed: ValueError: boom",
            ),
        ),
        calls,
    )

    with pytest.raises(NoValidLayout) as caught:
        pipeline.build(
            SMALL_URL,
            strategy="best",
            candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
            time_budget_s=STUB_RACE_BUDGET_S,
            race=True,
        )

    assert [failure.strategy for failure in caught.value.attempt_failures] == [
        "freeform",
        "sequence-pair",
    ]
    assert "was terminated" in str(caught.value)
    assert "ValueError: boom" in str(caught.value)


def test_every_raced_attempt_reports_its_wall_and_its_overshoot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wall stats Task 6 added are per-attempt, raced or not."""
    calls: list[dict[str, object]] = []
    _install_stub_race(
        monkeypatch,
        (
            strategy_race._StrategyRaceOutcome(
                "freeform", "completed", placement=_finished(2, 3)
            ),
            strategy_race._StrategyRaceOutcome(
                "sequence-pair", "completed", placement=_finished(3, 3)
            ),
        ),
        calls,
    )

    built = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=STUB_RACE_BUDGET_S,
        race=True,
    )

    assert len(built.attempts) == 2
    for attempt in built.attempts:
        stats = attempt.placement.stats
        assert stats["attempt_wall_s"] > 0.0
        assert stats["wall_overshoot_s"] == max(
            0.0,
            stats["attempt_wall_s"] - STUB_RACE_BUDGET_S - ATOMIC_COMPLETION_GRACE_S,
        )


#: A race that returns half a second INSIDE its own contract and half a second
#: past the atomic one -- the whole window where the two graces disagree.
RACED_WALL_S = STUB_RACE_BUDGET_S + strategy_race.RACE_COMPLETION_GRACE_S - 0.5


def test_a_raced_attempt_reports_overshoot_against_the_races_own_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The atomic grace is the wrong ruler for a pair the race owns.

    `run_strategy_race` waits until `budget + RACE_COMPLETION_GRACE_S` before it
    terminates an arm, so a race returning at 9.5 s into a 4.0 s budget spent
    exactly what it is allowed to.  Measured against the ATOMIC grace instead,
    that attempt reports `max(0.0, 9.5 - 4.0 - 5.0) = 0.5` s of overshoot that
    never happened -- and the gate reads overshoot.
    """
    assert ATOMIC_COMPLETION_GRACE_S < strategy_race.RACE_COMPLETION_GRACE_S
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    def spend_the_race() -> None:
        now[0] += RACED_WALL_S

    calls: list[dict[str, object]] = []
    _install_stub_race(
        monkeypatch,
        (
            strategy_race._StrategyRaceOutcome(
                "freeform", "completed", placement=_finished(2, 3)
            ),
            strategy_race._StrategyRaceOutcome(
                "sequence-pair", "completed", placement=_finished(3, 3)
            ),
        ),
        calls,
        on_call=spend_the_race,
    )

    built = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=STUB_RACE_BUDGET_S,
        race=True,
    )

    assert len(built.attempts) == 2
    for attempt in built.attempts:
        stats = attempt.placement.stats
        assert stats["attempt_wall_s"] == RACED_WALL_S
        assert stats["wall_overshoot_s"] == 0.0


def test_a_raced_attempt_is_not_born_deadline_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same grace decides the attempt's finalization deadline.

    An arm that hands back an unfinalized placement still has to be finalized
    here.  Its deadline is `race start + 4.0 + 6.0 = 1010.0` and the race
    returned at 1009.5, so `cancelled()` must read False.  Under the atomic
    grace the deadline is 1009.0 -- already past when the placement arrived --
    and the attempt is refused for a wall the race never blew.
    """
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    def spend_the_race() -> None:
        now[0] += RACED_WALL_S

    calls: list[dict[str, object]] = []
    _install_stub_race(
        monkeypatch,
        (
            strategy_race._StrategyRaceOutcome(
                "freeform",
                "completed",
                # A frame but no `completion`: the pipeline's compaction and
                # finalization branch is exactly what this test needs to run.
                placement=Placement(
                    buildings=(), completion=None, frame=AreaFrame(2, 3, 4, (4,), False)
                ),
            ),
            strategy_race._StrategyRaceOutcome.refused(
                "sequence-pair",
                "no arrangement fit the band",
                "no-proliferator",
                STUB_RACE_BUDGET_S,
            ),
        ),
        calls,
        on_call=spend_the_race,
    )
    polled: list[bool] = []

    def _finalize_spy(
        placement: Placement,
        _policy: object,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        assert cancelled is not None
        polled.append(cancelled())
        if polled[-1]:
            raise finalize.ProjectionCancelled
        return placement

    monkeypatch.setattr(
        finalize, "compact_open_boundary_belts", lambda placement, *_a, **_kw: placement
    )
    monkeypatch.setattr(finalize, "finalize_placement", _finalize_spy)

    built = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=STUB_RACE_BUDGET_S,
        race=True,
    )

    assert polled == [False]
    assert [attempt.strategy for attempt in built.attempts] == ["freeform"]
    assert [failure.strategy for failure in built.refused] == ["sequence-pair"]


def test_a_race_that_loses_an_arm_refuses_rather_than_reporting_a_full_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`total_pairs` promised two settlements, so one outcome is a lost arm.

    `run_strategy_race` filters its collector on both a present future and a
    known name, so a `submit` seam that returned fewer outcomes than arms would
    otherwise have the selection below pick a winner from the survivor without
    anything ever saying the other went missing.
    """
    calls: list[dict[str, object]] = []
    _install_stub_race(
        monkeypatch,
        (
            strategy_race._StrategyRaceOutcome(
                "freeform", "completed", placement=_finished(2, 3)
            ),
        ),
        calls,
    )

    with pytest.raises(ValueError, match="the race settled"):
        pipeline.build(
            SMALL_URL,
            strategy="best",
            candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
            time_budget_s=STUB_RACE_BUDGET_S,
            race=True,
        )

    assert len(calls) == 1


@pytest.mark.slow
def test_racing_best_produces_the_same_attempt_shape_as_the_serial_one() -> None:
    serial = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=8.0,
    )
    raced = pipeline.build(
        SMALL_URL,
        strategy="best",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        time_budget_s=8.0,
        race=True,
    )

    def shape(build: pipeline.Build) -> set[str | None]:
        return {a.strategy for a in build.attempts} | {f.strategy for f in build.refused}

    assert shape(raced) == shape(serial)
    assert len(raced.attempts) + len(raced.refused) == 2


@pytest.mark.slow
def test_a_stacked_url_belts_hydrogen_in_on_one_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ist=2`` with every technology researched: 40 items/s is 20 cargo/s,
    so one Mk.III entry lane carries it and no strip is shortened.

    This is the only end-to-end evidence of the stacked path: no corpus URL
    carries ``ist>1``, so the corpus gate cannot exercise the request-to-plan-
    to-emission contract.  The unstacked guard above proves the same 40 items/s
    still enters on two physical lanes when the bus carries one item per cargo.
    """
    _with_belt(monkeypatch, "conveyor-belt-3", stack=Fraction(2))
    build = pipeline.build(
        DEUTERON_URL,
        strategy="sequence-pair",
        time_budget_s=45.0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    )
    assert build.report.ok
    assert build.spec.belt_stack == 2
    hydrogen = [
        finding
        for finding in build.report.by_check("flow.external_entry_points")
        if finding.detail["item"] == "hydrogen"
    ]
    assert not hydrogen
