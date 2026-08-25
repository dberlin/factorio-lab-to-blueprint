"""A build is submitted and polled, and a refusal is one of the answers."""

from __future__ import annotations

import threading
import time

from flab2bp import pipeline
from flab2bp.layout.base import NoValidLayout
from flab2bp.web.jobs import Builder, Options

URL = "https://factoriolab.github.io/dsp/flow?o=graphene*60&v=11"


def _settled(builder: Builder, job_id: str, *, timeout_s: float = 20.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = builder.get(job_id)
        assert job is not None
        if job.done:
            return builder.snapshot(job)
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished")


def test_a_successful_build_reports_done_with_a_result(small_build: pipeline.Build) -> None:
    builder = Builder(solve=lambda _o, _p: small_build)
    try:
        job = builder.submit(Options(url=URL))
        snap = _settled(builder, job.id)
        assert snap["state"] == "done"
        assert snap["refusal"] is None and snap["error"] is None
        assert isinstance(snap["result"], dict)
        assert snap["result"]["blueprint"] == small_build.blueprint
    finally:
        builder.shutdown()


def test_a_refusal_is_a_result_not_an_error() -> None:
    """``NoValidLayout`` must not land in the same channel as a bad URL."""

    def refuse(_o: Options, _p: pipeline.ProgressSink) -> pipeline.Build:
        raise NoValidLayout(
            "spine/no-proliferator: too tall; freeform/no-proliferator: unroutable",
            spec_label="no-proliferator",
            budget_s=2.0,
        )

    builder = Builder(solve=refuse)
    try:
        snap = _settled(builder, builder.submit(Options(url=URL)).id)
        assert snap["state"] == "refused"
        assert snap["error"] is None
        assert isinstance(snap["refusal"], dict)
        # One line per strategy/candidate pair, not one long sentence.
        assert snap["refusal"]["reasons"] == [
            "spine/no-proliferator: too tall",
            "freeform/no-proliferator: unroutable",
        ]
        assert "no valid layout" in str(snap["refusal"]["message"])
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
        while builder.get(first.id).state != "running" and time.monotonic() < deadline:  # type: ignore[union-attr]
            time.sleep(0.01)
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
        options = Options(url=URL, strategy="best", candidates=2, budget_s=4.0)
        snap = _settled(builder, builder.submit(options).id)
        assert snap["solver_ceiling_s"] == 16.0
        assert isinstance(snap["elapsed_s"], float)
        reported = snap["options"]
        assert isinstance(reported, dict)
        assert reported["strategy"] == "best"
    finally:
        builder.shutdown()


def test_a_running_job_reports_which_pair_it_is_on(small_build: pipeline.Build) -> None:
    """Real progress, not elapsed time.

    Elapsed-against-a-ceiling was what this had before `pipeline.build` could
    say anything, and it could not tell a build stuck on its first candidate
    from one on its last.
    """
    reached_second = threading.Event()
    release = threading.Event()

    def solve(_o: Options, note: pipeline.ProgressSink) -> pipeline.Build:
        note(pipeline.AttemptProgress(1, 2, "no-proliferator", "spine", "started"))
        note(
            pipeline.AttemptProgress(
                1, 2, "no-proliferator", "spine", "refused", reason="too tall"
            )
        )
        note(pipeline.AttemptProgress(2, 2, "no-proliferator", "freeform", "started"))
        reached_second.set()
        release.wait(timeout=20.0)
        return small_build

    builder = Builder(solve=solve)
    try:
        job = builder.submit(Options(url=URL))
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
        assert [(s["strategy"], s["phase"], s["reason"]) for s in settled] == [
            ("spine", "refused", "too tall")
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
