from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.layout import finalize, route_kernel
from flab2bp.layout.base import (
    AreaFrame,
    LayoutAttemptFailure,
    NoValidLayout,
    PlacedBuilding,
    Placement,
    PlacementCompletion,
    ProjectionFailureRecord,
)
from flab2bp.rates import CandidatePolicy
from scripts import audit


def test_build_jobs_generates_one_powered_cell_per_run_plan_arm() -> None:
    entry = URL_CORPUS[0]

    jobs = audit.build_jobs(
        ["freeform"],
        {entry.tier},
        [1.0],
        workers=1,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        only={entry.url_id},
    )

    assert len(jobs) == 1
    assert jobs[0].power is True


def test_build_jobs_defaults_to_all_three_canonical_candidate_identities() -> None:
    entry = URL_CORPUS[0]

    jobs = audit.build_jobs(
        ["freeform"],
        {entry.tier},
        [1.0],
        workers=1,
        only={entry.url_id},
    )

    expected = (
        CandidatePolicy.NO_PROLIFERATOR,
        CandidatePolicy.ALL_PRODUCTS,
        CandidatePolicy.OUTPUT_PRODUCTS,
    )
    assert len(jobs) == 3
    assert all(job.candidate_policies == expected for job in jobs)
    assert tuple(job.candidate_policies[job.spec_index] for job in jobs) == expected



def test_run_cell_preserves_typed_refusal_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection_failure = ProjectionFailureRecord(
        band=3,
        check="geom.collide",
        buildings=(4, 9),
        detail="projected buildings overlap",
    )
    attempt_failure = LayoutAttemptFailure(
        candidate="height=17 arrangement=2",
        strategy="freeform",
        reason="candidate failed authoritative spherical projection",
        projection_failures=(projection_failure,),
    )
    reason = (
        "all attempted layouts failed authoritative spherical projection; "
        "retain this complete diagnostic beyond the compact terminal width"
    )
    refusal = NoValidLayout(
        reason,
        spec_label="evidence fixture",
        budget_s=1.0,
        attempt_failures=(attempt_failure,),
        projection_failures=(projection_failure,),
    )

    class RefusingStrategy:
        def lay_out(self, spec: object, *, time_budget_s: float) -> None:
            raise refusal

    monkeypatch.setattr(
        audit,
        "_specs_for",
        lambda url, candidate_policies: (SimpleNamespace(label="evidence fixture"),),
    )
    monkeypatch.setattr(
        audit,
        "_belt_rules_for",
        lambda url: SimpleNamespace(vertical_construction=False),
    )
    monkeypatch.setitem(
        audit._STRATEGIES,
        "evidence",
        lambda workers, vertical: RefusingStrategy(),
    )
    job = audit.Job(
        strategy="evidence",
        url_id="evidence",
        url="test://evidence",
        tier="trivial",
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=1,
    )

    result = audit.run_cell(job)

    assert result.status == "REFUSED"
    assert result.checks == ("<refused>",)
    assert result.attempt_failures == (attempt_failure,)
    assert result.projection_failures == (projection_failure,)
    assert result.detail == reason

    monkeypatch.setattr(audit, "_JSONL", [])
    audit.record({"evidence": audit.Tally()}, result)
    persisted = json.loads(json.dumps(audit._JSONL[-1]))

    expected_projection = {
        "band": 3,
        "check": "geom.collide",
        "buildings": [4, 9],
        "detail": "projected buildings overlap",
    }
    assert persisted["attempt_failures"] == [
        {
            "candidate": "height=17 arrangement=2",
            "strategy": "freeform",
            "reason": "candidate failed authoritative spherical projection",
            "projection_failures": [expected_projection],
        }
    ]
    assert persisted["projection_failures"] == [expected_projection]


def test_run_cell_persists_post_compaction_projection_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures = (
        finalize.ProjectionFailure(
            check="geom.collide",
            buildings=(2, 7),
            detail="projected colliders overlap",
            band=4,
        ),
        finalize.ProjectionFailure(
            check="power.coverage",
            buildings=(11,),
            detail="projected receiver is outside every power field",
            band=5,
        ),
    )
    refusal = finalize.ProjectionRefusal(failures)
    placement = Placement(buildings=())

    class SuccessfulStrategy:
        def lay_out(self, spec: object, *, time_budget_s: float) -> object:
            return placement

    monkeypatch.setattr(
        audit,
        "_specs_for",
        lambda url, candidate_policies: (SimpleNamespace(label="projection fixture"),),
    )
    monkeypatch.setattr(
        audit,
        "_belt_rules_for",
        lambda url: SimpleNamespace(vertical_construction=False),
    )
    monkeypatch.setitem(
        audit._STRATEGIES,
        "post-projection",
        lambda workers, vertical: SuccessfulStrategy(),
    )
    monkeypatch.setattr(
        "scripts.audit.finalize.compact_open_boundary_belts",
        lambda result, spec, *, expect_power: result,
    )

    def reject_projection(
        result: object,
        policy: object,
    ) -> object:
        raise refusal

    monkeypatch.setattr("scripts.audit.finalize.finalize_placement", reject_projection)
    monkeypatch.setattr(audit, "_JSONL", [])
    job = audit.Job(
        strategy="post-projection",
        url_id="projection",
        url="test://projection",
        tier="trivial",
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=1,
    )

    result = audit.run_cell(job)
    audit.record({"post-projection": audit.Tally()}, result)
    persisted = json.loads(json.dumps(audit._JSONL[-1]))

    expected = [
        {
            "band": 4,
            "check": "geom.collide",
            "buildings": [2, 7],
            "detail": "projected colliders overlap",
        },
        {
            "band": 5,
            "check": "power.coverage",
            "buildings": [11],
            "detail": "projected receiver is outside every power field",
        },
    ]
    assert result.status == "REFUSED"
    assert result.checks == ("geom.collide", "power.coverage")
    assert result.projection_failures == (
        ProjectionFailureRecord(
            band=4,
            check="geom.collide",
            buildings=(2, 7),
            detail="projected colliders overlap",
        ),
        ProjectionFailureRecord(
            band=5,
            check="power.coverage",
            buildings=(11,),
            detail="projected receiver is outside every power field",
        ),
    )
    assert persisted["projection_failures"] == expected


def test_run_cell_does_not_repeat_completed_placement_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buildings = (
        PlacedBuilding(
            item_id=2303,
            model_index=65,
            x=7,
            y=11,
            width=2,
            height=3,
        ),
    )
    frame = AreaFrame(2, 3, 4, (4,), False)
    completed = Placement(
        buildings=buildings,
        frame=frame,
        completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
    )
    completion_calls = {"compact": 0, "finalize": 0}
    certified: list[Placement] = []

    class CompletedStrategy:
        def lay_out(self, spec: object, *, time_budget_s: float) -> Placement:
            return completed

    def compact_spy(
        placement: Placement,
        spec: object,
        *,
        expect_power: bool,
    ) -> Placement:
        completion_calls["compact"] += 1
        return placement

    def finalize_spy(
        placement: Placement,
        policy: audit.BandPolicy,
    ) -> Placement:
        completion_calls["finalize"] += 1
        return placement

    def validate_spy(
        placement: Placement,
        spec: object,
        **kwargs: object,
    ) -> audit.validate.Report:
        certified.append(placement)
        return audit.validate.Report(findings=())

    monkeypatch.setattr(
        audit,
        "_specs_for",
        lambda url, candidate_policies: (SimpleNamespace(label="completed fixture"),),
    )
    monkeypatch.setattr(
        audit,
        "_belt_rules_for",
        lambda url: SimpleNamespace(vertical_construction=False, max_z=1),
    )
    monkeypatch.setitem(
        audit._STRATEGIES,
        "completed",
        lambda workers, vertical: CompletedStrategy(),
    )
    monkeypatch.setattr(audit.finalize, "compact_open_boundary_belts", compact_spy)
    monkeypatch.setattr(audit.finalize, "finalize_placement", finalize_spy)
    monkeypatch.setattr(audit.validate, "id_map", lambda spec: object())
    monkeypatch.setattr(audit.validate, "validate", validate_spy)
    monkeypatch.setattr(audit, "_JSONL", [])
    job = audit.Job(
        strategy="completed",
        url_id="completed",
        url="test://completed",
        tier="trivial",
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=1,
    )

    result = audit.run_cell(job)
    tallies = {"completed": audit.Tally()}
    audit.record(tallies, result)

    assert completion_calls == {"compact": 0, "finalize": 0}
    assert certified == [completed]
    assert certified[0].buildings is buildings
    assert certified[0].frame is frame
    assert certified[0].area == completed.area
    assert result.status == "CLEAN"
    assert result.area == completed.area
    assert tallies["completed"].clean == 1
    assert audit._JSONL[-1]["status"] == "CLEAN"
    assert audit._JSONL[-1]["area"] == completed.area


def test_run_cell_completes_unmarked_placement_once_and_preserves_invalid_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buildings = (
        PlacedBuilding(
            item_id=2303,
            model_index=65,
            x=3,
            y=5,
            width=2,
            height=3,
        ),
    )
    initial = Placement(buildings=buildings)
    compacted = replace(initial, stats={"projection_count": 1})
    frame = AreaFrame(2, 3, 4, (4,), False)
    finalized = replace(compacted, frame=frame)
    stages: list[str] = []
    certified: list[Placement] = []

    class UncompletedStrategy:
        def lay_out(self, spec: object, *, time_budget_s: float) -> Placement:
            return initial

    def compact_spy(
        placement: Placement,
        spec: object,
        *,
        expect_power: bool,
    ) -> Placement:
        stages.append("compact")
        assert placement is initial
        return compacted

    def finalize_spy(
        placement: Placement,
        policy: audit.BandPolicy,
    ) -> Placement:
        stages.append("finalize")
        assert placement is compacted
        return finalized

    findings = (
        audit.validate.Finding(
            check="geom.collide",
            severity=audit.validate.Severity.ERROR,
            message="overlap",
            buildings=(2, 7),
        ),
        audit.validate.Finding(
            check="power.coverage",
            severity=audit.validate.Severity.ERROR,
            message="unpowered",
            buildings=(11,),
        ),
    )

    def validate_spy(
        placement: Placement,
        spec: object,
        **kwargs: object,
    ) -> audit.validate.Report:
        stages.append("validate")
        certified.append(placement)
        return audit.validate.Report(findings=findings)

    monkeypatch.setattr(
        audit,
        "_specs_for",
        lambda url, candidate_policies: (SimpleNamespace(label="ordinary fixture"),),
    )
    monkeypatch.setattr(
        audit,
        "_belt_rules_for",
        lambda url: SimpleNamespace(vertical_construction=False, max_z=1),
    )
    monkeypatch.setitem(
        audit._STRATEGIES,
        "ordinary",
        lambda workers, vertical: UncompletedStrategy(),
    )
    monkeypatch.setattr(audit.finalize, "compact_open_boundary_belts", compact_spy)
    monkeypatch.setattr(audit.finalize, "finalize_placement", finalize_spy)
    monkeypatch.setattr(audit.validate, "id_map", lambda spec: object())
    monkeypatch.setattr(audit.validate, "validate", validate_spy)
    job = audit.Job(
        strategy="ordinary",
        url_id="ordinary",
        url="test://ordinary",
        tier="trivial",
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=1,
    )

    result = audit.run_cell(job)

    assert stages == ["compact", "finalize", "validate"]
    assert len(certified) == 1
    assert certified[0].completion is PlacementCompletion.COMPACTED_AND_FINALIZED
    assert certified[0].buildings is buildings
    assert certified[0].frame is frame
    assert certified[0].area == finalized.area
    assert result.status == "INVALID"
    assert result.checks == ("geom.collide", "power.coverage")
    assert result.detail == "2e geom.collide,power.coverage"


def test_every_audit_row_carries_the_routing_backend_and_the_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    monkeypatch.setattr(audit, "_JSONL", [])
    job = audit.Job(
        strategy="freeform",
        url_id=URL_CORPUS[0].url_id,
        url=URL_CORPUS[0].url,
        tier=URL_CORPUS[0].tier.value,
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=1,
    )
    # `Tally.total` is a read-only property summing the counters, so a Tally is
    # constructed EMPTY and grows as `record` classifies each result.
    tallies = {"freeform": audit.Tally()}
    for status, detail in (("CLEAN", ""), ("REFUSED", "deadline exhausted")):
        audit.record(
            tallies,
            audit.Result(job, status, "no-proliferator", detail, (), 1.0),
        )

    assert tallies["freeform"].total == 2
    assert len(audit._JSONL) == 2
    # Equality against the real selector, not membership in its two-value
    # range: a `Result.route_backend` field hard-coded to a literal "cython"
    # default would still pass a membership check but is not what shipped --
    # it is not a live read of the process's actual routing kernel.
    expected_backend = route_kernel.selected_backend()
    for row in audit._JSONL:
        assert row["commit"] == "0123456789abcdef0123456789abcdef01234567"
        assert row["route_backend"] == expected_backend


def test_result_route_backend_field_defaults_via_the_live_selector_not_a_literal() -> (
    None
):
    # This box has a compiled kernel, so `route_kernel.selected_backend()` and a
    # field hard-coded to `"cython"` are the SAME string right now -- a test
    # that only compares the constructed value (even against a fresh call to
    # `selected_backend()`) cannot tell them apart on this box. Assert on the
    # field's wiring instead: a `default_factory` identical to the live
    # selector function is present only when the field calls it; a baked-in
    # default has no `default_factory` at all (`dataclasses.MISSING`).
    fields = {f.name: f for f in dataclasses.fields(audit.Result)}
    assert fields["route_backend"].default_factory is route_kernel.selected_backend


def test_head_commit_is_a_hash_or_the_word_unknown() -> None:
    commit = audit._head_commit()

    assert commit == "unknown" or (len(commit) == 40 and int(commit, 16) >= 0)


def test_head_commit_falls_back_to_unknown_when_git_cannot_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", _raise)

    assert audit._head_commit() == "unknown"


def test_main_resolves_and_stamps_the_commit_it_reads_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Drives `main()` itself rather than `record()` directly, so that deleting
    # the `global _COMMIT; _COMMIT = _head_commit()` line inside `main` --
    # which would leave every row silently stamped "unknown" -- is caught.
    # `build_jobs` and `run_cell` are replaced with a single canned job/result
    # so the test exercises `main`'s wiring without running a real solve.
    monkeypatch.setattr(audit, "_JSONL", [])
    monkeypatch.setattr(audit, "_COMMIT", "unknown")
    resolved_commit = "f" * 40
    monkeypatch.setattr(audit, "_head_commit", lambda: resolved_commit)
    job = audit.Job(
        strategy="freeform",
        url_id=URL_CORPUS[0].url_id,
        url=URL_CORPUS[0].url,
        tier=URL_CORPUS[0].tier.value,
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=1,
    )
    monkeypatch.setattr(audit, "build_jobs", lambda *args, **kwargs: [job])
    monkeypatch.setattr(
        audit,
        "run_cell",
        lambda j: audit.Result(j, "CLEAN", "no-proliferator", "", (), 0.01),
    )
    monkeypatch.setattr(sys, "argv", ["audit.py", "--jobs", "1"])

    exit_code = audit.main()

    assert exit_code == 0
    assert len(audit._JSONL) == 1
    assert audit._JSONL[0]["commit"] == resolved_commit
    assert audit._JSONL[0]["commit"] != "unknown"
    assert audit._JSONL[0]["commit"] == audit._head_commit()
