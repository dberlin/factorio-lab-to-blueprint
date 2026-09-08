"""A build is submitted and polled, and a refusal is one of the answers."""

from __future__ import annotations

import dataclasses
import queue
import threading
import time
from pathlib import Path
from typing import cast

import httpx
import pytest

from flab2bp import pipeline
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.layout.band_policy import BAND_SELECTIONS
from flab2bp.layout.base import (
    LayoutAttemptFailure,
    NoValidLayout,
    ProjectionFailureRecord,
)
from flab2bp.layout.observe import SearchObserver
from flab2bp.rates import DEFAULT_CANDIDATE_POLICIES, CandidatePolicy
from flab2bp.web import jobs as jobs_module
from flab2bp.web.jobs import Builder, InvalidOptions, Options, parse_options, run_build
from flab2bp.web.payload import Json, JsonValue
from flab2bp.web.server import serve

_BELT_RULES = belt_rules_for_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*60&v=11")


URL = "https://factoriolab.github.io/dsp/flow?o=graphene*60&v=11"


def test_web_power_override_reaches_pipeline_and_is_echoed(
    monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build
) -> None:
    def solve(url: str, **kwargs: object) -> pipeline.Build:
        assert kwargs["power_tower"] == "substation"
        return small_build

    monkeypatch.setattr(pipeline, "build", solve)
    builder = Builder()
    try:
        job = builder.submit(parse_options({"url": URL, "power_tower": "substation"}))
        snapshot = _settled(builder, job.id)
        assert snapshot["state"] == "done"
        assert _object(snapshot["options"])["power_tower"] == "substation"
    finally:
        builder.shutdown()


@pytest.mark.parametrize("legacy_power", [False, True])
def test_server_rejects_legacy_power_payload(
    legacy_power: bool,
    small_build: pipeline.Build,
    tmp_path: Path,
) -> None:
    httpd, builder = serve(
        port=0,
        dist=tmp_path,
        solve=lambda _options, _progress, _s=None, _t=None: small_build,
    )
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
    builder = Builder(solve=lambda _o, _p, _s=None, _t=None: small_build)
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
    builder = Builder(solve=lambda _o, _p, _s=None, _t=None: unframed)
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

    def refuse(
        _o: Options,
        _p: pipeline.ProgressSink,
        _s: SearchObserver | None = None,
        _t: object | None = None,
    ) -> pipeline.Build:
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
    def refuse(
        _o: Options,
        _p: pipeline.ProgressSink,
        _s: SearchObserver | None = None,
        _t: object | None = None,
    ) -> pipeline.Build:
        raise NoValidLayout(
            "request has no legal layout",
            spec_label="direct-spec",
            budget_s=1.0,
            stats={
                "process_wall_time_s": 1.25,
                "process_peak_rss_kib": 123_456,
            },
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
            "stats": {
                "process_wall_time_s": 1.25,
                "process_peak_rss_kib": 123_456,
            },
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
        stats={
            "process_wall_time_s": 8.0,
            "pipeline_finalization_time_s": 1.5,
        },
    )

    def refuse(
        _o: Options,
        _p: pipeline.ProgressSink,
        _s: SearchObserver | None = None,
        _t: object | None = None,
    ) -> pipeline.Build:
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
        assert serialized["stats"] == {
            "process_wall_time_s": 8.0,
            "pipeline_finalization_time_s": 1.5,
        }
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
    def blow_up(
        _o: Options,
        _p: pipeline.ProgressSink,
        _s: SearchObserver | None = None,
        _t: object | None = None,
    ) -> pipeline.Build:
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
    def disconnect(
        _o: Options,
        _p: pipeline.ProgressSink,
        _s: SearchObserver | None = None,
        _t: object | None = None,
    ) -> pipeline.Build:
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


def test_a_collector_whose_start_fails_still_lets_the_queue_close(
    monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build
) -> None:
    """Critical 1: `TraceCollector.start()` used to bind `self._thread` BEFORE
    `thread.start()`. If starting the thread ever raised (OS thread
    exhaustion), `stop()` would then try to join a thread that was never
    started, which raises `RuntimeError` -- and that raise happened inside
    `Builder._run`'s `finally`, BEFORE the trace queue's own
    `cancel_join_thread()`/`close()`. In a long-lived web process, that leaks
    the spawn-context `multiprocessing.Queue`, its feeder thread, and its
    pipe fds on every job whose trace collector failed to start.

    Reproduced here by making the REAL `threading.Thread.start()` raise, but
    only for the trace collector's own thread (named "flab2bp-trace") -- so
    the fix under test is `TraceCollector.start()`'s actual bind-after-start
    ordering, not a stand-in for it, and every other thread in the process
    (the builder's own pool, this test's polling) is untouched.
    """
    closed: list[str] = []

    class _TrackingQueue:
        def get_nowait(self) -> object:
            raise queue.Empty

        def put_nowait(self, item: object) -> None:
            raise NotImplementedError

        def cancel_join_thread(self) -> None:
            closed.append("cancel_join_thread")

        def close(self) -> None:
            closed.append("close")

    class _FakeContext:
        def Queue(self, maxsize: int = 0) -> object:
            return _TrackingQueue()

    monkeypatch.setattr(jobs_module.multiprocessing, "get_context", lambda kind: _FakeContext())

    real_start = threading.Thread.start

    def failing_start(self: threading.Thread) -> None:
        if self.name == "flab2bp-trace":
            raise RuntimeError("can't start new thread")
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", failing_start)

    builder = Builder(solve=lambda *_a, **_k: small_build)
    try:
        job = builder.submit(Options(url=URL, trace=True))
        snap = _settled(builder, job.id, timeout_s=2.0)

        assert snap["state"] == "error"
        assert closed == ["cancel_join_thread", "close"]
    finally:
        builder.shutdown()


def _gate_trace_feeder(trace_queue, sent, release, payload_bytes) -> None:
    """Gate a real feeder after either a complete frame or interrupted framing."""
    import struct

    send_bytes = trace_queue._send_bytes

    def partial_send(payload) -> None:
        if payload_bytes is None:
            send_bytes(payload)
        elif payload_bytes == -1:
            trace_queue._writer._send(struct.pack("!i", len(payload))[:1])
        elif payload_bytes == -2:
            send_bytes(b"")
        else:
            trace_queue._writer._send(struct.pack("!i", len(payload)))
            if payload_bytes:
                trace_queue._writer._send(payload[:payload_bytes])
        sent.set()
        release.wait()

    trace_queue._send_bytes = partial_send


def _interrupt_trace_feeder(trace_queue, sent, release, payload_bytes) -> None:
    from flab2bp.layout.observe import SearchEvent, SearchPhase

    _gate_trace_feeder(trace_queue, sent, release, payload_bytes)
    trace_queue.put_nowait(
        SearchEvent(strategy="freeform", candidate="interrupted", phase=SearchPhase.INCUMBENT)
    )
    release.wait()


_normal_trace_queue = None
_normal_trace_sent = None


def _prepare_normal_trace_exit(trace_queue, sent, release, payload_bytes) -> None:
    global _normal_trace_queue, _normal_trace_sent
    _normal_trace_queue, _normal_trace_sent = trace_queue, sent
    _gate_trace_feeder(trace_queue, sent, release, payload_bytes)


def _return_normal_trace_outcome():
    from flab2bp.layout.observe import SearchEvent, SearchPhase
    from flab2bp.layout.observe_channel import TraceChannel
    from flab2bp.layout.strategy_race import _StrategyRaceOutcome

    assert _normal_trace_queue is not None and _normal_trace_sent is not None
    channel = TraceChannel(_normal_trace_queue)
    channel.offer(
        SearchEvent(strategy="freeform", candidate="interrupted", phase=SearchPhase.INCUMBENT)
    )
    assert _normal_trace_sent.wait(10)
    channel.close()
    return _StrategyRaceOutcome("freeform", "refused", refusal_reason="normal solver result")


@pytest.mark.parametrize(
    "collector_failed", [False, True], ids=["partial-write", "failed-collector"]
)
def test_normal_trace_producer_exit_keeps_result_and_advances_next_build(
    monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build, collector_failed: bool
) -> None:
    _terminated_trace_scenario(
        monkeypatch, small_build, 1, normal_return=True, collector_failed=collector_failed
    )


@pytest.mark.parametrize(
    "payload_bytes",
    [-1, -2, 0, 1],
    ids=["partial-header", "empty-pickle", "header-only", "partial-payload"],
)
def test_interrupted_trace_write_reports_failure_and_next_build_starts(
    monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build, payload_bytes: int
) -> None:
    """Killing a real feeder mid-frame cannot pin the sole Builder worker."""
    _terminated_trace_scenario(monkeypatch, small_build, payload_bytes)


def test_clean_trace_stays_complete_when_a_producer_is_terminated(
    monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build
) -> None:
    _terminated_trace_scenario(monkeypatch, small_build, None)


def test_real_trace_queue_keeps_delayed_final_frame_after_normal_producer_exit(
    monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build
) -> None:
    _terminated_trace_scenario(
        monkeypatch, small_build, None, normal_return=True, delay_reader=True
    )


def _terminated_trace_scenario(
    monkeypatch: pytest.MonkeyPatch,
    small_build: pipeline.Build,
    payload_bytes: int | None,
    *,
    normal_return: bool = False,
    collector_failed: bool = False,
    delay_reader: bool = False,
) -> None:
    import multiprocessing
    from concurrent.futures import Future, ProcessPoolExecutor

    from flab2bp.layout.band_policy import BandPolicy
    from flab2bp.layout.observe import SearchEvent, SearchPhase
    from flab2bp.layout.strategy_race import _StrategyRaceOutcome, run_strategy_race
    from flab2bp.web import trace as trace_module
    from flab2bp.web.trace import TraceCollector
    from tests.layout.test_freeform import two_stage_spec

    context = multiprocessing.get_context("spawn")
    sent, release = context.Event(), context.Event()
    read_entered = threading.Event()
    prior_published = threading.Event()
    race_returned = threading.Event()
    next_started = threading.Event()
    projection_failed = threading.Event()
    reader_release = threading.Event()
    timed_stop_returned = threading.Event()
    queues, pools, workers, managers = [], [], [], []
    real_drain = TraceCollector.drain_once
    real_frame = trace_module.frame_json
    real_stop = TraceCollector.stop

    def observed_stop(self, *, timeout=2.0):
        stopped = real_stop(self, timeout=timeout)
        if timeout is not None:
            timed_stop_returned.set()
        return stopped

    def maybe_failed_frame(seq, at_s, event):
        if event.candidate == "projection-failure":
            projection_failed.set()
            raise ValueError("trace projection failed")
        return real_frame(seq, at_s, event)

    def observed_drain(self: TraceCollector) -> None:
        real_drain(self)
        if self.ring.since(-1)[0]:
            prior_published.set()

    def submit(requests, channels, trace_queue=None):
        pool = ProcessPoolExecutor(
            max_workers=1,
            mp_context=context,
            max_tasks_per_child=1 if normal_return else None,
            initializer=_prepare_normal_trace_exit if normal_return else _interrupt_trace_feeder,
            initargs=(trace_queue, sent, release, payload_bytes),
        )
        pools.append(pool)
        blocked = (
            pool.submit(_return_normal_trace_outcome) if normal_return else pool.submit(int, 0)
        )
        workers.extend(pool._processes.values())
        managers.append(pool._executor_manager_thread)
        assert sent.wait(10), "child feeder never wrote its partial payload"
        if not collector_failed:
            assert read_entered.wait(10), "collector never entered the blocking receive"
        print("TRACE PROBE gated producer confirmed", flush=True)
        peer = Future()
        peer.set_result(_StrategyRaceOutcome("sequence-pair", "refused", refusal_reason="peer"))
        return {blocked: "freeform", peer: "sequence-pair"}, pool

    def solve(options, progress, observer, trace_queue):
        if not options.trace:
            next_started.set()
            return small_build
        queues.append(trace_queue)
        recv_bytes = trace_queue._recv_bytes

        def observed_recv():
            read_entered.set()
            if delay_reader:
                assert reader_release.wait(10), "probe never released its healthy reader"
            return recv_bytes()

        trace_queue._recv_bytes = observed_recv
        observer.note(
            SearchEvent(strategy="freeform", candidate="prior", phase=SearchPhase.INCUMBENT)
        )
        assert prior_published.wait(10), "healthy frame was not published before the fault"
        print("TRACE PROBE prior frame published", flush=True)
        if collector_failed:
            observer.note(
                SearchEvent(
                    strategy="freeform", candidate="projection-failure", phase=SearchPhase.INCUMBENT
                )
            )
            assert projection_failed.wait(10), "collector never failed its projection"
        ticks = iter((0.0, 0.0 if normal_return else 1000.0))
        outcomes = run_strategy_race(
            two_stage_spec(),
            time_budget_s=0.1,
            band_policy=BandPolicy("portable"),
            belt_rules=_BELT_RULES,
            share=False,
            trace_queue=trace_queue,
            submit=submit,
            monotonic=lambda: next(ticks),
        )
        expected_status = "refused" if normal_return else "terminated"
        assert [outcome.status for outcome in outcomes] == [expected_status, "refused"]
        if normal_return:
            assert outcomes[0].refusal_reason == "normal solver result"
        print("TRACE PROBE race returned", flush=True)
        race_returned.set()
        if normal_return:
            return small_build
        raise ValueError("solver rejected after interrupted race")

    monkeypatch.setattr(TraceCollector, "drain_once", observed_drain)
    monkeypatch.setattr(trace_module, "frame_json", maybe_failed_frame)
    monkeypatch.setattr(TraceCollector, "stop", observed_stop)
    builder = Builder(solve=solve)
    job = None
    try:
        job = builder.submit(Options(url=URL, trace=True))
        queued = builder.submit(Options(url=URL))
        assert race_returned.wait(15), "race deadline never returned"
        snapshot = _settled(builder, job.id)
        if normal_return:
            assert snapshot["state"] == "done"
        else:
            assert snapshot["error"] == "solver rejected after interrupted race"
        if delay_reader:
            assert timed_stop_returned.wait(5), "collector did not reach its timed stop"
            assert not next_started.is_set()
            page = builder.trace_page(job, 0)
            assert page["frames"] == [] and page["complete"] is False
            reader_release.set()
        assert next_started.wait(5), "interrupted trace pinned the only Builder worker"
        assert _settled(builder, queued.id)["state"] == "done"
        assert job.trace is not None
        assert job.trace._thread is not None and not job.trace._thread.is_alive()
        frames = builder.trace_page(job, -1)
        expected = ["prior", "interrupted"] if payload_bytes is None else ["prior"]
        assert [_object(frame)["candidate"] for frame in frames["frames"]] == expected
        assert frames["complete"] is False
        final = builder.trace_page(job, frames["next"])
        if payload_bytes is None:
            assert job.trace.closed and job.trace.error is None
            assert final["complete"] is True
        else:
            assert not job.trace.closed
            assert "trace collection failed" in final["error"]
        assert not any(worker.is_alive() for worker in workers)
        assert not any(manager.is_alive() for manager in managers)
    finally:
        print("TRACE PROBE reaping owned producers", flush=True)
        reader_release.set()
        # RED cleanup: kill/reap only these owned producers, then half-close
        # their verified parent's WRITE end. Never close under the reader.
        # Never set an Event used by a killed child: termination can strand
        # its condition lock. This is a kill-only gate, not a release handshake.
        for pool in pools:
            for worker in tuple((pool._processes or {}).values()):
                if worker.is_alive():
                    worker.kill()
            pool.shutdown(wait=False, cancel_futures=True)
        for worker in workers:
            if worker.is_alive():
                worker.kill()
        for manager in managers:
            manager.join(10)
            assert not manager.is_alive(), "probe producer cleanup failed"
        print("TRACE PROBE producers reaped; half-closing parent writer", flush=True)
        for trace_queue in queues:
            trace_queue._writer.close()
        if job is not None and job.trace is not None:
            job.trace.stop(timeout=5)
            assert job.trace._thread is None or not job.trace._thread.is_alive()
        print("TRACE PROBE reader settled; joining Builder worker", flush=True)
        builder._pool.shutdown(wait=False, cancel_futures=True)
        for thread in builder._pool._threads:
            thread.join(10)
            assert not thread.is_alive(), "probe could not settle its Builder worker"


def test_terminal_job_keeps_polling_until_delayed_collector_drains_and_closes(
    monkeypatch: pytest.MonkeyPatch, small_build: pipeline.Build
) -> None:
    from flab2bp.layout.observe import SearchEvent, SearchPhase
    from flab2bp.web.trace import TraceCollector

    entered = threading.Event()
    release = threading.Event()
    queue_closed = threading.Event()
    stop_returned = threading.Event()
    real_drain = TraceCollector.drain_once
    real_stop = TraceCollector.stop
    real_join = threading.Thread.join

    class TrackingQueue(queue.Queue[object]):
        def get_nowait(self) -> object:
            if queue_closed.is_set():
                raise AssertionError("queue closed underneath the collector")
            return super().get_nowait()

        def cancel_join_thread(self) -> None:
            pass

        def close(self) -> None:
            queue_closed.set()

    trace_queue = TrackingQueue()

    class FakeContext:
        def Queue(self, maxsize: int = 0) -> object:
            return trace_queue

    def delayed_drain(self: TraceCollector) -> None:
        entered.set()
        assert release.wait(5), "test never released the final drain"
        real_drain(self)

    def immediate_join(self: threading.Thread, timeout: float | None = None) -> None:
        real_join(
            self, timeout=0 if self.name == "flab2bp-trace" and timeout is not None else timeout
        )

    def observed_stop(self: TraceCollector, *, timeout: float | None = 2.0) -> bool:
        result = real_stop(self, timeout=timeout)
        stop_returned.set()
        return result

    def solve(*_args: object) -> pipeline.Build:
        assert entered.wait(2)
        trace_queue.put_nowait(
            SearchEvent(strategy="freeform", candidate="final", phase=SearchPhase.INCUMBENT)
        )
        return small_build

    monkeypatch.setattr(jobs_module.multiprocessing, "get_context", lambda kind: FakeContext())
    monkeypatch.setattr(TraceCollector, "drain_once", delayed_drain)
    monkeypatch.setattr(TraceCollector, "stop", observed_stop)
    monkeypatch.setattr(threading.Thread, "join", immediate_join)
    builder = Builder(solve=solve)
    try:
        job = builder.submit(Options(url=URL, trace=True))
        assert _settled(builder, job.id, timeout_s=2)["state"] == "done"
        assert stop_returned.wait(2), "stop did not reach its timeout"
        empty = builder.trace_page(job, -1)
        assert empty["frames"] == []
        assert empty["complete"] is False
        assert not queue_closed.is_set()

        release.set()
        assert queue_closed.wait(2), "queue was not released after the reader finished"
        final = builder.trace_page(job, -1)
        assert [
            (_object(frame)["seq"], _object(frame)["candidate"])
            for frame in cast(list[JsonValue], final["frames"])
        ] == [(0, "final")]
        assert final["complete"] is False
        exhausted = builder.trace_page(job, cast(int, final["next"]))
        assert exhausted["frames"] == []
        assert exhausted["complete"] is True
        assert exhausted["dropped"] == 0
        assert exhausted["evicted"] == 0
    finally:
        release.set()
        builder._pool.shutdown(wait=True, cancel_futures=True)


def test_collector_failure_preserves_published_frames_then_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flab2bp.layout.observe import SearchEvent, SearchPhase
    from flab2bp.web import trace as trace_module
    from flab2bp.web.jobs import Job
    from flab2bp.web.trace import TraceCollector, TraceRing

    real_frame = trace_module.frame_json

    def failing_frame(seq: int, at_s: float, event: SearchEvent) -> Json:
        if event.candidate == "broken":
            raise ValueError("broken projection")
        return real_frame(seq, at_s, event)

    monkeypatch.setattr(trace_module, "frame_json", failing_frame)
    collector = TraceCollector(TraceRing(), started_at=time.monotonic())
    for candidate in ("published", "broken"):
        collector.observer.note(
            SearchEvent(strategy="freeform", candidate=candidate, phase=SearchPhase.INCUMBENT)
        )
    job = Job("failed-trace", Options(url=URL, trace=True), time.monotonic(), state="done")
    job.trace = collector
    builder = Builder()
    try:
        assert collector.stop() is False
        assert collector.closed is False
        page = builder.trace_page(job, -1)
        assert [_object(frame)["candidate"] for frame in cast(list[JsonValue], page["frames"])] == [
            "published"
        ]
        assert page["complete"] is False
        assert builder.trace_page(job, cast(int, page["next"])) == {
            "error": "trace collection failed: broken projection"
        }
        assert builder.snapshot(job)["state"] == "done"
    finally:
        builder.shutdown()


def test_collector_failure_keeps_complete_frames_from_the_same_queue_pass() -> None:
    import multiprocessing

    from flab2bp.layout.observe import SearchEvent, SearchPhase
    from flab2bp.layout.observe_channel import prepare_trace_queue
    from flab2bp.web.jobs import Job
    from flab2bp.web.trace import TraceCollector, TraceRing

    transport = multiprocessing.get_context("spawn").Queue(maxsize=4)
    prepare_trace_queue(transport)
    sent = threading.Event()
    send_bytes = transport._send_bytes
    messages = 0

    def corrupt_second_message(payload):
        nonlocal messages
        messages += 1
        send_bytes(payload if messages == 1 else b"")
        if messages == 2:
            sent.set()

    transport._send_bytes = corrupt_second_message
    collector = TraceCollector(TraceRing(), started_at=time.monotonic(), queue=transport)
    collector.observer.note(
        SearchEvent(strategy="freeform", candidate="serial-pending", phase=SearchPhase.INCUMBENT)
    )
    job = Job("same-pass-error", Options(url=URL, trace=True), time.monotonic(), state="done")
    job.trace = collector
    builder = Builder()
    try:
        transport.put_nowait(
            SearchEvent(
                strategy="freeform", candidate="queue-complete", phase=SearchPhase.INCUMBENT
            )
        )
        transport.put_nowait("malformed second message")
        assert sent.wait(5), "feeder did not finish both transport frames"
        assert collector.stop() is False
        assert not collector.closed
        page = builder.trace_page(job, -1)
        assert [_object(frame)["candidate"] for frame in cast(list[JsonValue], page["frames"])] == [
            "serial-pending",
            "queue-complete",
        ]
        assert page["complete"] is False
        assert "trace collection failed" in builder.trace_page(job, page["next"])["error"]
        assert builder.snapshot(job)["state"] == "done"
    finally:
        # Both writes already completed; no producer or live reader is blocked.
        transport.close()
        if transport._thread is not None:
            transport._thread.join(5)
            assert not transport._thread.is_alive(), "probe feeder did not terminate"
        transport._reader.close()
        transport._writer.close()
        builder.shutdown()


@pytest.mark.parametrize("failure", [OSError("broken pipe"), ValueError("closed queue")])
def test_broken_trace_queue_is_failure_not_successful_empty_completion(failure: Exception) -> None:
    from flab2bp.layout.observe import SearchEvent, SearchPhase
    from flab2bp.web.jobs import Job
    from flab2bp.web.trace import TraceCollector, TraceRing

    class BrokenQueue:
        def get_nowait(self) -> object:
            raise failure

    collector = TraceCollector(TraceRing(), started_at=time.monotonic())
    collector.observer.note(
        SearchEvent(strategy="freeform", candidate="published", phase=SearchPhase.INCUMBENT)
    )
    collector.drain_once()
    collector.queue = BrokenQueue()
    job = Job("broken-queue", Options(url=URL, trace=True), time.monotonic(), state="done")
    job.trace = collector
    builder = Builder()
    try:
        assert collector.stop() is False
        assert collector.closed is False
        published = builder.trace_page(job, -1)
        assert [
            _object(frame)["candidate"] for frame in cast(list[JsonValue], published["frames"])
        ] == ["published"]
        assert published["complete"] is False
        assert builder.trace_page(job, cast(int, published["next"])) == {
            "error": f"trace collection failed: {failure}"
        }
        assert builder.snapshot(job)["state"] == "done"
    finally:
        builder.shutdown()


#: ``iron-ore`` is mining-only -- see ``tests/test_pipeline.py``'s
#: ``NO_BUILDABLE_RECIPE_URL`` for why this is infeasible by construction
#: rather than by budget or layout luck. ``rates.solve`` raises a bare
#: ``InfeasibleError`` for it, which is a ``RuntimeError`` -- exactly the shape
#: ``test_an_unexpected_operational_failure_finishes_as_error`` above shows
#: landing in ``error`` with the generic "build failed unexpectedly" message
#: today. This exercises the REAL ``run_build`` (not a stub), because the fix
#: belongs to ``pipeline.build`` translating the exception, not to this module.
NO_BUILDABLE_RECIPE_URL = "https://factoriolab.github.io/dsp/flow?o=iron-ore*60&v=11"


def test_an_infeasible_spec_is_a_refusal_not_an_unexpected_failure() -> None:
    builder = Builder(solve=run_build)
    try:
        job = builder.submit(Options(url=NO_BUILDABLE_RECIPE_URL, budget_s=1.0))
        snap = _settled(builder, job.id, timeout_s=20.0)
        assert snap["state"] == "refused"
        assert snap["error"] is None
        assert snap["result"] is None
        refused = _object(snap["refusal"])
        assert "iron-ore" in str(refused["message"])
        assert "Traceback" not in str(refused["message"])
    finally:
        builder.shutdown()


def test_a_second_job_queues_behind_the_first(small_build: pipeline.Build) -> None:
    """One worker, so the second job waits -- and says how far back it is."""
    release = threading.Event()

    def wait_then_build(
        _o: Options,
        _p: pipeline.ProgressSink,
        _s: SearchObserver | None = None,
        _t: object | None = None,
    ) -> pipeline.Build:
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
    builder = Builder(history=3, solve=lambda _o, _p, _s=None, _t=None: small_build)
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
    builder = Builder(solve=lambda _o, _p, _s=None, _t=None: small_build)
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
    def solve(
        _options: Options,
        note: pipeline.ProgressSink,
        _s: SearchObserver | None = None,
        _t: object | None = None,
    ) -> pipeline.Build:
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
    def solve(
        _options: Options,
        note: pipeline.ProgressSink,
        _s: SearchObserver | None = None,
        _t: object | None = None,
    ) -> pipeline.Build:
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

    def solve(
        _o: Options,
        note: pipeline.ProgressSink,
        _s: SearchObserver | None = None,
        _t: object | None = None,
    ) -> pipeline.Build:
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
    builder = Builder(solve=lambda _o, _p, _s=None, _t=None: small_build)
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
    builder = Builder(solve=lambda _o, _p, _s=None, _t=None: small_build)
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
        builder = Builder(solve=lambda _o, _p, _s=None, _t=None: small_build)
        try:
            job = builder.submit(Options(url=URL, flow="Recipes\nid,name\ngraphene,Graphene\n"))
            snap = _settled(builder, job.id)
            options = _object(snap["options"])
            assert options["flow_supplied"] is True
            assert "flow" not in options
        finally:
            builder.shutdown()
