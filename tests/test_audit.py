"""Behavioral checks for the corpus audit entry point."""

from collections.abc import Iterable, MutableSequence
from concurrent.futures import Future, wait
from fractions import Fraction
from types import SimpleNamespace
from typing import cast

import pytest

from flab2bp.bench import runner
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.dsp import catalog
from flab2bp.layout import validate
from flab2bp.layout.base import (
    AreaFrame,
    LayoutStrategy,
    PlacedBuilding,
    Placement,
    PlacementCompletion,
)
from flab2bp.rates import CandidatePolicy
from flab2bp.spec import BuildSpec
from scripts import ab_compare, audit


def test_both_selects_all_implemented_strategies() -> None:
    assert audit.strategy_names("both") == ("freeform", "sequence-pair")


def test_machine_rank_arm_reaches_every_policy_and_placer_job() -> None:
    from flab2bp.bench.corpus import Tier

    jobs = audit.build_jobs(
        ["freeform", "sequence-pair"],
        set(Tier),
        [30],
        workers=1,
        only={"iron-ingot"},
        machine_rank="up-to",
    )
    assert len(jobs) == 6
    assert {job.machine_rank for job in jobs} == {"up-to"}
    assert audit.build_parser().parse_args([]).machine_rank == "exact"


@pytest.mark.parametrize("seam", ["audit", "bench", "ab"])
def test_judges_reject_save_restricted_belt_geometry(
    seam: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropping either researched field changes these real physical findings."""
    spec = BuildSpec(groups=(), label="policy")
    placement = Placement(
        buildings=(
            PlacedBuilding(2001, catalog.building(2001).model_index, 0, 0, output_obj=1),
            PlacedBuilding(2001, catalog.building(2001).model_index, 0, 0, z=Fraction(1)),
            PlacedBuilding(2001, catalog.building(2001).model_index, 3, 0, z=Fraction(20)),
        ),
        frame=AreaFrame(4, 1, 4, (4,), False),
        completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
    )

    class FixedLayout:
        def lay_out(self, spec: BuildSpec, *, time_budget_s: float) -> Placement:
            return placement

    handle = runner.StrategyHandle("freeform", cast(LayoutStrategy, FixedLayout()))
    monkeypatch.setattr(audit, "_specs_for", lambda *args, **kwargs: (spec,))
    monkeypatch.setitem(audit._STRATEGIES, "freeform", lambda *args: handle.strategy)
    entry = URL_CORPUS[0]
    job = audit.Job(
        "freeform",
        entry.url_id,
        entry.url,
        entry.tier.value,
        0,
        (CandidatePolicy.NO_PROLIFERATOR,),
        1.0,
        1,
    )
    rules = (
        catalog.BeltAltitudeRules(Fraction(1), False, 1, 3, True),
        catalog.BeltAltitudeRules(Fraction(38), True, 8, 15, False),
    )
    findings = []
    for policy in rules:
        if seam == "audit":
            checks = audit.run_cell(job, belt_rules=policy).checks
        elif seam == "bench":
            checks = runner._run_cell(
                handle,
                entry,
                spec,
                time_budget_s=1.0,
                belt_rules=policy,
                ids=validate.id_map(spec),
            ).error_checks
        else:
            _, checks = ab_compare.judge_with(
                spec,
                validate.id_map(spec),
                placement,
                belt_rules=policy,
            )
        findings.append(set(checks))
    physical = {"geom.altitude_step", "geom.altitude_range"}
    assert physical <= findings[0]
    assert not physical & findings[1]
    assert findings[0] - physical == findings[1]


def test_terminal_job_outcomes_keep_their_selected_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = audit.build_jobs(
        ["freeform", "sequence-pair"],
        {URL_CORPUS[0].tier},
        [1.0],
        workers=1,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        only={URL_CORPUS[0].url_id},
    )
    monkeypatch.setattr(audit, "_JSONL", [])
    tallies = {job.strategy: audit.Tally() for job in jobs}
    audit.record(tallies, audit.Result(jobs[1], "CLEAN", "plain", "", (), 0.1))
    audit.record(tallies, audit.Result(jobs[0], "TERMINATED", "?", "audit cap", (), 1.0))
    assert (tallies["freeform"].clean, tallies["freeform"].not_run) == (0, 1)
    assert (tallies["sequence-pair"].clean, tallies["sequence-pair"].not_run) == (1, 0)
    assert all(tally.total == 1 for tally in tallies.values())
    assert {(row["strategy"], row["status"]) for row in audit._JSONL} == {
        ("sequence-pair", "CLEAN"),
        ("freeform", "TERMINATED"),
    }


@pytest.mark.parametrize("completed_at_cutoff", [False, True])
def test_audit_cutoff_harvests_actual_jobs_not_a_completion_prefix(
    completed_at_cutoff: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = audit.build_jobs(
        ["freeform", "sequence-pair"],
        {URL_CORPUS[0].tier},
        [1.0],
        workers=1,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        only={URL_CORPUS[0].url_id},
    )
    rules = catalog.BeltAltitudeRules(Fraction(38), True, 8, 15, False)
    clock = [0.0]
    slow: Future[audit.Result] = Future()

    class ControlledPool:
        def __init__(self, **kwargs: object) -> None:
            initargs = cast(tuple[object, object, MutableSequence[int]], kwargs["initargs"])
            self.started = initargs[2]

        def submit(self, function: object, *args: object) -> Future[object]:
            if function is audit._belt_rules_for:
                prepared: Future[object] = Future()
                prepared.set_result(rules)
                return prepared
            job_id, job, _rules = args
            assert isinstance(job_id, int) and isinstance(job, audit.Job)
            self.started[job_id] = 1
            if job_id == 0:
                return cast(Future[object], slow)
            fast: Future[object] = Future()
            fast.set_result(audit.Result(job, "CLEAN", "plain", "", (), 0.1))
            return fast

    def cutoff_after_fast(
        futures: Iterable[Future[object]], *, timeout: float, return_when: str
    ) -> tuple[set[Future[object]], set[Future[object]]]:
        finished, pending = wait(futures, timeout=0, return_when=return_when)
        if any(isinstance(future.result(), audit.Result) for future in finished):
            if completed_at_cutoff:
                slow.set_result(audit.Result(jobs[0], "REFUSED", "plain", "no layout", (), 1.0))
            clock[0] = 2.0
        return finished, pending

    monkeypatch.setattr(audit, "ProcessPoolExecutor", ControlledPool)
    monkeypatch.setattr(audit, "_stop_audit_workers", lambda *args: None)
    monkeypatch.setattr(audit, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(audit, "wait", cutoff_after_fast)
    published: list[audit.Result] = []
    terminal = audit._run_jobs(jobs, workers=2, deadline=1.0, publish=published.append)
    assert {key: result.status for key, result in terminal.items()} == {
        0: "REFUSED" if completed_at_cutoff else "TERMINATED",
        1: "CLEAN",
    }
    assert [result.job for result in published] == [jobs[1], jobs[0]]


def _interrupt_audit_result_writer(sent, release, groups, lock, started) -> None:
    import struct
    from multiprocessing.connection import Connection

    audit._initialize_audit_worker(groups, lock, started)

    def partial_send(writer, payload) -> None:
        writer._send(struct.pack("!i", len(payload)))
        writer._send(payload[:1])
        sent.set()
        release.wait(15.0)

    Connection._send_bytes = partial_send


def test_audit_cutoff_settles_an_interrupted_result_reader() -> None:
    """Reaping workers alone leaves the interpreter blocked on its manager."""
    import multiprocessing as mp
    import threading
    import time
    from concurrent.futures import ProcessPoolExecutor

    context = mp.get_context("spawn")
    sent, release = context.Event(), context.Event()
    groups = context.RawArray("q", 1)
    started = context.RawArray("b", 1)
    receiving = threading.Event()
    prior_children = frozenset(child.pid for child in mp.active_children() if child.pid is not None)
    pool = ProcessPoolExecutor(
        max_workers=1,
        mp_context=context,
        initializer=_interrupt_audit_result_writer,
        initargs=(sent, release, groups, context.Lock(), started),
    )
    result_queue = pool._result_queue
    original_recv = result_queue._reader.recv
    children, manager = [], None

    def observed_recv():
        receiving.set()
        return original_recv()

    result_queue._reader.recv = observed_recv
    try:
        pool.submit(int, 0)
        children = [child for child in mp.active_children() if child.pid not in prior_children]
        manager = pool._executor_manager_thread
        assert sent.wait(10.0), "worker never wrote a partial result"
        assert receiving.wait(10.0), "manager never entered the interrupted receive"
        before = time.monotonic()
        audit._stop_audit_workers(pool, groups, prior_children)
        assert time.monotonic() - before < 2.0
        assert not any(child.is_alive() for child in children)
        assert manager is not None and not manager.is_alive()
    finally:
        # Retain our real owners even if the production cleanup discarded its
        # handles. Never touch a semaphore gate after killing its waiting owner.
        for child in children:
            if child.is_alive():
                child.kill()
        pool.shutdown(wait=False, cancel_futures=True)
        stop_by = time.monotonic() + 2.0
        for child in children:
            child.join(max(0.0, stop_by - time.monotonic()))
            assert not child.is_alive(), "probe could not reap its result writer"
        result_queue._writer.close()
        if manager is not None:
            manager.join(max(0.0, stop_by - time.monotonic()))
            assert not manager.is_alive(), "probe could not settle its result reader"
