"""A build is submitted and polled, and a refusal is one of the answers."""

from __future__ import annotations

import dataclasses
import threading
import time
from pathlib import Path

import httpx
import pytest

from flab2bp import pipeline
from flab2bp.layout.band_policy import BAND_SELECTIONS
from flab2bp.layout.base import (
    LayoutAttemptFailure,
    NoValidLayout,
    ProjectionFailureRecord,
)
from flab2bp.rates import DEFAULT_CANDIDATE_POLICIES, CandidatePolicy
from flab2bp.web.jobs import Builder, InvalidOptions, Options, parse_options, run_build
from flab2bp.web.payload import Json, JsonValue
from flab2bp.web.server import serve

URL = "https://factoriolab.github.io/dsp/flow?o=graphene*60&v=11"


@pytest.mark.parametrize("legacy_power", [False, True])
def test_server_rejects_legacy_power_payload(
    legacy_power: bool,
    small_build: pipeline.Build,
    tmp_path: Path,
) -> None:
    httpd, builder = serve(port=0, dist=tmp_path, solve=lambda _options, _progress: small_build)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        response = httpx.post(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/build",
            json={"url": URL, "power": legacy_power},
        )
        assert response.status_code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
        builder.shutdown()
        thread.join(timeout=5)


def _settled(builder: Builder, job_id: str, *, timeout_s: float = 20.0) -> Json:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = builder.get(job_id)
        assert job is not None
        if job.done:
            return builder.snapshot(job)
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished")


def _object(value: JsonValue) -> Json:
    if not isinstance(value, dict):
        raise AssertionError(f"expected JSON object, got {value!r}")
    return value


def test_a_successful_build_reports_done_with_a_result(small_build: pipeline.Build) -> None:
    builder = Builder(solve=lambda _o, _p: small_build)
    try:
        job = builder.submit(Options(url=URL))
        snap = _settled(builder, job.id)
        assert snap["state"] == "done"
        assert snap["refusal"] is None and snap["error"] is None
        result = _object(snap["result"])
        assert result["blueprint"] == small_build.blueprint
    finally:
        builder.shutdown()


def test_unframed_success_finishes_as_controlled_error(
    small_build: pipeline.Build,
) -> None:
    unframed = dataclasses.replace(
        small_build,
        placement=dataclasses.replace(
            small_build.placement,
            frame=None,
            completion=None,
        ),
    )
    builder = Builder(solve=lambda _o, _p: unframed)
    try:
        job = builder.submit(Options(url=URL))
        snap = _settled(builder, job.id, timeout_s=1.0)
        assert snap["state"] == "error"
        assert snap["error"] == "successful build placement has no area frame"
        assert snap["result"] is None and snap["refusal"] is None
        current = builder.get(job.id)
        assert current is not None
        assert current.finished_at is not None
    finally:
        builder.shutdown()


def test_a_refusal_is_a_result_not_an_error() -> None:
    """``NoValidLayout`` must not land in the same channel as a bad URL."""

    def refuse(_o: Options, _p: pipeline.ProgressSink) -> pipeline.Build:
        raise NoValidLayout(
            "freeform/no-proliferator: too tall; freeform/max-proliferation: unroutable",
            spec_label="no-proliferator",
            budget_s=2.0,
            attempt_reasons=(
                "freeform/no-proliferator: too tall",
                "freeform/max-proliferation: unroutable",
            ),
            attempt_failures=(
                LayoutAttemptFailure("no-proliferator", "freeform", "too tall"),
                LayoutAttemptFailure("max-proliferation", "freeform", "unroutable"),
            ),
        )

    builder = Builder(solve=refuse)
    try:
        snap = _settled(builder, builder.submit(Options(url=URL)).id)
        assert snap["state"] == "refused"
        assert snap["error"] is None
        refused = _object(snap["refusal"])
        attempts = refused["attempts"]
        assert isinstance(attempts, list)
        assert [
            (_object(attempt)["candidate"], _object(attempt)["reason"]) for attempt in attempts
        ] == [
            ("no-proliferator", "too tall"),
            ("max-proliferation", "unroutable"),
        ]
        assert "no valid layout" in str(refused["message"])
    finally:
        builder.shutdown()


def test_direct_refusal_without_attempt_strategy_serializes_null_not_an_invalid_name() -> None:
    def refuse(_o: Options, _p: pipeline.ProgressSink) -> pipeline.Build:
        raise NoValidLayout(
            "request has no legal layout",
            spec_label="direct-spec",
            budget_s=1.0,
        )

    builder = Builder(solve=refuse)
    try:
        snap = _settled(builder, builder.submit(Options(url=URL)).id)
        refused = _object(snap["refusal"])
        attempts = refused["attempts"]
        assert isinstance(attempts, list) and len(attempts) == 1
        direct = _object(attempts[0])
        assert direct == {
            "candidate": "direct-spec",
            "strategy": None,
            "reason": "request has no legal layout",
            "projection_failures": [],
        }
    finally:
        builder.shutdown()


def test_projection_evidence_semicolons_stay_structured_inside_attempt_payload() -> None:
    first = ProjectionFailureRecord(
        160,
        "geom.collide",
        (4, 9),
        "first projected collision; left collider; right collider",
    )
    second = ProjectionFailureRecord(
        200,
        "game.power_too_close",
        (2, 7),
        "projected power envelopes intersect; north; south",
    )
    attempt = LayoutAttemptFailure(
        "no-proliferator",
        "sequence-pair",
        "no scheduled stage produced an exact layout; exact validation failed",
        (first, second),
    )

    def refuse(_o: Options, _p: pipeline.ProgressSink) -> pipeline.Build:
        raise NoValidLayout(
            attempt.reason,
            spec_label=attempt.candidate,
            budget_s=2.0,
            attempt_reasons=(str(attempt),),
            attempt_failures=(attempt,),
            projection_failures=(first, second),
        )

    builder = Builder(solve=refuse)
    try:
        snap = _settled(builder, builder.submit(Options(url=URL)).id)
        refused = _object(snap["refusal"])
        attempts = refused["attempts"]
        assert isinstance(attempts, list) and len(attempts) == 1
        serialized = _object(attempts[0])
        assert serialized["reason"] == attempt.reason
        assert serialized["projection_failures"] == [
            {
                "band": 160,
                "check": "geom.collide",
                "buildings": [4, 9],
                "detail": "first projected collision; left collider; right collider",
            },
            {
                "band": 200,
                "check": "game.power_too_close",
                "buildings": [2, 7],
                "detail": "projected power envelopes intersect; north; south",
            },
        ]
    finally:
        builder.shutdown()


def test_a_bad_url_is_an_error() -> None:
    def blow_up(_o: Options, _p: pipeline.ProgressSink) -> pipeline.Build:
        raise ValueError("that is not a FactorioLab URL")

    builder = Builder(solve=blow_up)
    try:
        snap = _settled(builder, builder.submit(Options(url=URL)).id)
        assert snap["state"] == "error"
        assert snap["error"] == "that is not a FactorioLab URL"
        assert snap["refusal"] is None and snap["result"] is None
    finally:
        builder.shutdown()


def test_an_unexpected_operational_failure_finishes_as_error() -> None:
    def disconnect(_o: Options, _p: pipeline.ProgressSink) -> pipeline.Build:
        raise RuntimeError("CDP connection dropped")

    builder = Builder(solve=disconnect)
    try:
        job = builder.submit(Options(url=URL))
        snap = _settled(builder, job.id, timeout_s=1.0)
        assert snap["state"] == "error"
        assert snap["error"] == "build failed unexpectedly"
        assert snap["refusal"] is None and snap["result"] is None
        current = builder.get(job.id)
        assert current is not None
        assert current.finished_at is not None
    finally:
        builder.shutdown()


def test_a_second_job_queues_behind_the_first(small_build: pipeline.Build) -> None:
    """One worker, so the second job waits -- and says how far back it is."""
    release = threading.Event()

    def wait_then_build(_o: Options, _p: pipeline.ProgressSink) -> pipeline.Build:
        release.wait(timeout=20.0)
        return small_build

    builder = Builder(workers=1, solve=wait_then_build)
    try:
        first = builder.submit(Options(url=URL))
        second = builder.submit(Options(url=URL))
        # The first job has to actually reach the worker before the second can
        # be behind it; without this the assertion could pass vacuously.
        deadline = time.monotonic() + 5.0
        current = builder.get(first.id)
        while current is not None and current.state != "running" and time.monotonic() < deadline:
            time.sleep(0.01)
            current = builder.get(first.id)
        assert builder.snapshot(second)["state"] == "queued"
        assert builder.snapshot(second)["queue_position"] == 0
        release.set()
        assert _settled(builder, second.id)["state"] == "done"
    finally:
        release.set()
        builder.shutdown()


def test_old_finished_jobs_are_evicted_and_running_ones_are_not(
    small_build: pipeline.Build,
) -> None:
    builder = Builder(history=3, solve=lambda _o, _p: small_build)
    try:
        # One at a time: submitting six at once would have them evicted out from
        # under the poll, which is eviction working, not eviction under test.
        ids: list[str] = []
        for _ in range(6):
            job = builder.submit(Options(url=URL))
            ids.append(job.id)
            _settled(builder, job.id)
        alive = [job_id for job_id in ids if builder.get(job_id) is not None]
        assert len(alive) <= 3
        # The survivors are the most recent ones, which is what a poll wants.
        assert alive == ids[-len(alive) :]
    finally:
        builder.shutdown()


def test_the_snapshot_carries_the_ceiling_and_the_elapsed_time(
    small_build: pipeline.Build,
) -> None:
    builder = Builder(solve=lambda _o, _p: small_build)
    try:
        options = Options(
            url=URL,
            strategy="best",
            candidate_policies=(
                CandidatePolicy.NO_PROLIFERATOR,
                CandidatePolicy.ALL_PRODUCTS,
            ),
            budget_s=4.0,
        )
        snap = _settled(builder, builder.submit(options).id)
        assert snap["solver_ceiling_s"] == 2 * pipeline.PRODUCTION_STRATEGY_COUNT * 4.0
        assert isinstance(snap["elapsed_s"], float)
        reported = snap["options"]
        assert isinstance(reported, dict)
        assert reported["strategy"] == "best"
        assert reported["candidate_policies"] == [
            CandidatePolicy.NO_PROLIFERATOR.value,
            CandidatePolicy.ALL_PRODUCTS.value,
        ]
        assert "candidates" not in reported
    finally:
        builder.shutdown()


def test_progress_total_comes_from_the_pipeline(
    small_build: pipeline.Build,
) -> None:
    def solve(_options: Options, note: pipeline.ProgressSink) -> pipeline.Build:
        note(
            pipeline.AttemptProgress(
                1,
                99,
                "observed-candidate",
                "freeform",
                "started",
            )
        )
        return small_build

    builder = Builder(solve=solve)
    try:
        job = builder.submit(
            Options(
                url=URL,
                strategy="freeform",
                candidate_policies=(
                    CandidatePolicy.NO_PROLIFERATOR,
                    CandidatePolicy.OUTPUT_PRODUCTS,
                ),
            )
        )
        snap = _settled(builder, job.id)
        progress = _object(snap["progress"])
        assert progress["total"] == 99
    finally:
        builder.shutdown()


def test_filtered_pipeline_total_is_not_replaced_by_the_request_ceiling(
    small_build: pipeline.Build,
) -> None:
    def solve(_options: Options, note: pipeline.ProgressSink) -> pipeline.Build:
        note(
            pipeline.AttemptProgress(
                1,
                1,
                "surviving-candidate",
                "freeform",
                "started",
            )
        )
        return small_build

    builder = Builder(solve=solve)
    try:
        job = builder.submit(
            Options(
                url=URL,
                strategy="freeform",
                candidate_policies=(
                    CandidatePolicy.NO_PROLIFERATOR,
                    CandidatePolicy.OUTPUT_PRODUCTS,
                ),
            )
        )
        snap = _settled(builder, job.id)
        progress = _object(snap["progress"])
        assert progress["total"] == 1
    finally:
        builder.shutdown()


def test_a_running_job_reports_which_pair_it_is_on(small_build: pipeline.Build) -> None:
    """Real progress, not elapsed time.

    Elapsed-against-a-ceiling was what this had before `pipeline.build` could
    say anything, and it could not tell a build stuck on its first candidate
    from one on its last.
    """
    reached_second = threading.Event()
    projection = ProjectionFailureRecord(
        band=7,
        check="routing; blocked",
        buildings=(4, 5),
        detail="north; south",
    )
    release = threading.Event()

    def solve(_o: Options, note: pipeline.ProgressSink) -> pipeline.Build:
        note(pipeline.AttemptProgress(1, 2, "no-proliferator", "freeform", "started"))
        note(
            pipeline.AttemptProgress(
                1,
                2,
                "no-proliferator",
                "freeform",
                "refused",
                reason="too tall",
                projection_failures=(projection,),
            )
        )
        note(pipeline.AttemptProgress(2, 2, "max-proliferation", "freeform", "started"))
        reached_second.set()
        release.wait(timeout=20.0)
        return small_build

    builder = Builder(solve=solve)
    try:
        job = builder.submit(
            Options(
                url=URL,
                strategy="freeform",
                candidate_policies=(
                    CandidatePolicy.NO_PROLIFERATOR,
                    CandidatePolicy.ALL_PRODUCTS,
                ),
            )
        )
        assert reached_second.wait(timeout=20.0)
        snap = builder.snapshot(job)
        progress = snap["progress"]
        assert isinstance(progress, dict)
        assert (progress["index"], progress["total"]) == (2, 2)
        assert progress["strategy"] == "freeform"
        assert progress["phase"] == "started"
        # A pair that already gave up stays visible while the next one runs;
        # `started` events are not kept, or every pair would appear twice.
        settled = snap["settled"]
        assert isinstance(settled, list)
        settled_objects = [_object(item) for item in settled]
        assert [(item["strategy"], item["phase"], item["reason"]) for item in settled_objects] == [
            ("freeform", "refused", "too tall")
        ]
        assert settled_objects[0]["projection_failures"] == [
            {
                "band": 7,
                "check": "routing; blocked",
                "buildings": [4, 5],
                "detail": "north; south",
            }
        ]
    finally:
        release.set()
        builder.shutdown()


def test_a_job_that_has_not_started_laying_out_claims_no_progress(
    small_build: pipeline.Build,
) -> None:
    """Parsing the URL and solving the rates come first and take an unknown time."""
    builder = Builder(solve=lambda _o, _p: small_build)
    try:
        snap = _settled(builder, builder.submit(Options(url=URL)).id)
        assert snap["progress"] is None
        assert snap["settled"] == []
    finally:
        builder.shutdown()


def test_band_defaults_to_portable_and_accepts_exact_dimensions() -> None:
    assert parse_options({"url": URL}).band == "portable"
    assert (
        tuple(parse_options({"url": URL, "band": selection}).band for selection in BAND_SELECTIONS)
        == BAND_SELECTIONS
    )
    assert parse_options({"url": URL, "band": "160"}).band == "50x800"
    assert parse_options({"url": URL, "band": "200"}).band == "160x1000"

    for value in (160, None, "240", "Portable"):
        with pytest.raises(InvalidOptions, match="'band'"):
            parse_options({"url": URL, "band": value})


def test_run_build_passes_band_to_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def spy(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)
        raise ValueError("stop after observing options")

    monkeypatch.setattr(pipeline, "build", spy)
    with pytest.raises(ValueError, match="stop after observing"):
        run_build(Options(url=URL, band="160x1000"), lambda _step: None)

    assert seen["band"] == "160x1000"


def test_run_build_passes_the_exact_candidate_policy_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def spy(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)
        raise ValueError("stop after observing options")

    monkeypatch.setattr(pipeline, "build", spy)
    selected = (
        CandidatePolicy.NO_PROLIFERATOR,
        CandidatePolicy.OUTPUT_PRODUCTS,
    )
    with pytest.raises(ValueError, match="stop after observing"):
        run_build(
            Options(
                url=URL,
                strategy="freeform",
                candidate_policies=selected,
            ),
            lambda _step: None,
        )

    assert seen["candidate_policies"] == selected


def test_run_build_delegates_default_cpu_allocation_to_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    small_build: pipeline.Build,
) -> None:
    """Web and direct builds use the pipeline's one allocation policy."""
    calls: list[dict[str, object]] = []

    def solve_once(*_args: object, **kwargs: object) -> pipeline.Build:
        calls.append(dict(kwargs))
        return small_build

    monkeypatch.setattr(pipeline, "build", solve_once)
    selected = (
        CandidatePolicy.NO_PROLIFERATOR,
        CandidatePolicy.ALL_PRODUCTS,
    )

    built = run_build(
        Options(
            url=URL,
            candidate_policies=selected,
        ),
        lambda _step: None,
    )

    assert built is small_build
    assert len(calls) == 1
    assert calls[0]["candidate_policies"] == selected
    assert calls[0]["race"] is True
    assert "workers" not in calls[0]
    assert "candidate_parallelism" not in calls[0]




def test_pinned_flow_snapshot_advertises_one_effective_candidate(
    small_build: pipeline.Build,
) -> None:
    builder = Builder(solve=lambda _o, _p: small_build)
    try:
        options = Options(
            url=URL,
            candidate_policies=DEFAULT_CANDIDATE_POLICIES,
            flow="Recipes\nid,name\ngraphene,Graphene\n",
            budget_s=4.0,
        )
        snap = _settled(builder, builder.submit(options).id)
        assert snap["solver_ceiling_s"] == pipeline.PRODUCTION_STRATEGY_COUNT * 4.0
    finally:
        builder.shutdown()


def test_run_build_does_not_forward_the_retired_power_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def spy(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)
        raise ValueError("stop after observing options")

    monkeypatch.setattr(pipeline, "build", spy)
    with pytest.raises(ValueError, match="stop after observing"):
        run_build(Options(url=URL), lambda _step: None)

    assert "power" not in seen


def test_run_build_passes_fetch_flow_and_web_url_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def spy(*_args: object, **kwargs: object) -> object:
        seen.update(kwargs)
        raise ValueError("stop after observing options")

    monkeypatch.setattr(pipeline, "build", spy)
    with pytest.raises(ValueError, match="stop after observing"):
        run_build(Options(url=URL, fetch_flow=True), lambda _step: None)

    assert seen["fetch_flow"] is True
    validator = seen["fetch_url_validator"]
    assert callable(validator)


class TestFlowReachesTheSolver:
    """``run_build`` is the one call into ``pipeline.build``.

    Checked by intercepting that call rather than by solving: what matters here
    is that the CSV the request carried arrives as ``flow_text`` and is not
    quietly dropped, which would report a derived build as though it were the
    pinned one the user asked for.
    """

    def test_the_csv_arrives_as_flow_text(
        self, monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build
    ) -> None:
        seen: dict[str, object] = {}

        def spy(url: str, **kwargs: object) -> pipeline.Build:
            seen.update(kwargs)
            return small_build

        monkeypatch.setattr(pipeline, "build", spy)
        csv = "Recipes\nid,name\ngraphene,Graphene\n"
        run_build(Options(url=URL, flow=csv), lambda _s: None)
        assert seen["flow_text"] == csv

    def test_no_flow_means_none_not_an_empty_string(
        self, monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build
    ) -> None:
        # `flow_text=""` would reach `flow_from_text("")` and refuse. Absent
        # has to stay absent.
        seen: dict[str, object] = {}

        def spy(url: str, **kwargs: object) -> pipeline.Build:
            seen.update(kwargs)
            return small_build

        monkeypatch.setattr(pipeline, "build", spy)
        run_build(Options(url=URL), lambda _s: None)
        assert seen["flow_text"] is None

    def test_explicit_proliferator_tier_reaches_pipeline(
        self, monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build
    ) -> None:
        from flab2bp.rates.adjust import ProliferatorTier

        seen: dict[str, object] = {}

        def spy(url: str, **kwargs: object) -> pipeline.Build:
            seen.update(kwargs)
            return small_build

        monkeypatch.setattr(pipeline, "build", spy)
        run_build(
            Options(url=URL, proliferator_tier=ProliferatorTier.MK1),
            lambda _s: None,
        )
        assert seen["proliferator_tier"] is ProliferatorTier.MK1

    def test_the_snapshot_says_whether_one_was_supplied(self, small_build: pipeline.Build) -> None:
        # The CSV itself is not echoed back -- it can be hundreds of kB and the
        # page already has it -- but silence about whether one was used would
        # leave a poller unable to tell a dropped flow from an absent one.
        builder = Builder(solve=lambda _o, _p: small_build)
        try:
            job = builder.submit(Options(url=URL, flow="Recipes\nid,name\ngraphene,Graphene\n"))
            snap = _settled(builder, job.id)
            options = _object(snap["options"])
            assert options["flow_supplied"] is True
            assert "flow" not in options
        finally:
            builder.shutdown()
