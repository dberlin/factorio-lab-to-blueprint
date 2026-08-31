from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.layout import finalize
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
