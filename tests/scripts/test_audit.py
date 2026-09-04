from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import time
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

import pytest

from flab2bp.bench.corpus import URL_CORPUS, Tier
from flab2bp.dsp import catalog
from flab2bp.layout import finalize, route_kernel, validate
from flab2bp.layout.base import (
    ATOMIC_COMPLETION_GRACE_S,
    AreaFrame,
    LayoutAttemptFailure,
    NoValidLayout,
    PlacedBuilding,
    Placement,
    PlacementCompletion,
    ProjectionFailureRecord,
)
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.layout.strategy_race import RACE_COMPLETION_GRACE_S, RacingLayout
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
        lambda url: SimpleNamespace(vertical_construction=False, max_z=1),
    )
    monkeypatch.setitem(
        audit._STRATEGIES,
        "evidence",
        lambda workers, vertical, _max_belt_z: RefusingStrategy(),
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
    # Driven clock, no sleeping: a projection refusal REJECTS a placement the
    # attempt already built, so it spent its whole budget and the row must
    # still carry a wall and an overshoot -- unlike a NoValidLayout refusal,
    # which never had a placement to charge for.
    now = [500.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
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
        lambda url: SimpleNamespace(vertical_construction=False, max_z=1),
    )
    monkeypatch.setitem(
        audit._STRATEGIES,
        "post-projection",
        lambda workers, vertical, _max_belt_z: SuccessfulStrategy(),
    )
    def compact_stub(result: object, spec: object, *, expect_power: bool) -> object:
        now[0] += 4.0
        return result

    monkeypatch.setattr(
        "scripts.audit.finalize.compact_open_boundary_belts",
        compact_stub,
    )

    def reject_projection(
        result: object,
        policy: object,
    ) -> object:
        now[0] += 3.0
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
    # The attempt ran 500.0 -> 507.0 (compact +4.0, then the projection refusal
    # +3.0) = 7.0s wall; 7.0 - budget(1.0) - ATOMIC_COMPLETION_GRACE_S(5.0) ==
    # 1.0, clamped at 0.  A refusal AFTER a placement existed is not the same
    # as a refusal that never built one: this row is honest carrying both.
    assert result.attempt_wall_s == pytest.approx(7.0)
    assert result.wall_overshoot_s == pytest.approx(1.0)
    assert persisted["attempt_wall_s"] == pytest.approx(7.0)
    assert persisted["wall_overshoot_s"] == pytest.approx(1.0)


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
        lambda workers, vertical, _max_belt_z: CompletedStrategy(),
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
        lambda workers, vertical, _max_belt_z: UncompletedStrategy(),
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


def test_all_resolves_to_the_two_strategies_and_the_portfolio() -> None:
    assert audit.strategy_names("all") == ("freeform", "sequence-pair", "best")
    assert audit.strategy_names("both") == ("freeform", "sequence-pair")


def test_the_best_cell_builds_a_racing_layout_at_the_cells_belt_ceiling() -> None:
    # NOT `catalog.DEFAULT_MAX_BELT_Z`: `RacingLayout.max_belt_z` defaults to
    # exactly that, so a factory that DROPS the argument still constructs a
    # layout carrying it and a test at the default value cannot see the drop.
    ceiling = Fraction(23, 4)
    assert ceiling != catalog.DEFAULT_MAX_BELT_Z

    layout = audit._STRATEGIES["best"](6, True, ceiling)

    assert isinstance(layout, RacingLayout)
    assert layout.workers == 6
    assert layout.belt_vertical_construction is True
    # The child validates its own incumbent before publishing it; validating at
    # a different ceiling from `run_cell`'s would publish a bound the cell then
    # rejects.
    assert layout.max_belt_z == ceiling


def test_the_two_explicit_factories_ignore_the_belt_ceiling() -> None:
    assert isinstance(
        audit._STRATEGIES["freeform"](4, True, Fraction(171, 20)), FreeformLayout
    )
    assert isinstance(
        audit._STRATEGIES["sequence-pair"](4, True, Fraction(171, 20)),
        SequencePairLayout,
    )


def test_a_full_all_strategy_run_plans_one_hundred_and_eight_cells() -> None:
    jobs = audit.build_jobs(
        list(audit.strategy_names("all")),
        set(Tier),
        [30.0],
        8,
    )

    # 12 corpus URLs x 3 candidate policies x 3 strategies.
    assert len(jobs) == 108


def test_run_cell_builds_the_strategy_at_the_cells_own_belt_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `run_cell` validates the winner at `belt_rules.max_z`, so a racing child
    # handed a DIFFERENT ceiling would certify an incumbent this very cell then
    # rejects.  The ceiling below is deliberately NOT
    # `catalog.DEFAULT_MAX_BELT_Z`, or a `run_cell` that passed the module
    # default instead of this cell's own rules would go unnoticed.
    ceiling = Fraction(23, 4)
    assert ceiling != catalog.DEFAULT_MAX_BELT_Z
    seen: list[tuple[int, bool, Fraction]] = []

    class _RefusingStrategy:
        def lay_out(self, spec: object, *, time_budget_s: float) -> None:
            raise NoValidLayout("nothing to lay out", spec_label="ceiling fixture")

    def _factory(
        workers: int,
        vertical: bool,
        max_belt_z: Fraction,
    ) -> _RefusingStrategy:
        seen.append((workers, vertical, max_belt_z))
        return _RefusingStrategy()

    monkeypatch.setattr(
        audit,
        "_specs_for",
        lambda url, candidate_policies: (SimpleNamespace(label="ceiling fixture"),),
    )
    monkeypatch.setattr(
        audit,
        "_belt_rules_for",
        lambda url: SimpleNamespace(vertical_construction=True, max_z=ceiling),
    )
    monkeypatch.setitem(audit._STRATEGIES, "ceiling", _factory)
    job = audit.Job(
        strategy="ceiling",
        url_id="ceiling",
        url="test://ceiling",
        tier="trivial",
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=5,
    )

    result = audit.run_cell(job)

    assert result.status == "REFUSED"
    assert seen == [(5, True, ceiling)]


def test_a_clean_cell_reports_its_attempt_wall_and_the_overshoot_past_the_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Driven clock, no sleeping: `now[0]` is the only time source `run_cell`
    # sees, and the stub strategy advances it by exactly the wall under test.
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    completed = Placement(
        buildings=(
            PlacedBuilding(item_id=2303, model_index=65, x=0, y=0, width=2, height=3),
        ),
        frame=AreaFrame(2, 3, 4, (4,), False),
        completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
    )

    class _SlowStrategy:
        def lay_out(self, spec: object, *, time_budget_s: float) -> Placement:
            now[0] += 20.0
            return completed

    def _slow_specs(
        url: str,
        candidate_policies: object,
    ) -> tuple[SimpleNamespace, ...]:
        # Building the spec is the CELL's cost, not the attempt's, and the two
        # spans differ by exactly this: a wall measured from `t0` would charge
        # the layout for work it never did.
        now[0] += 3.0
        return (SimpleNamespace(label="slow fixture"),)

    monkeypatch.setattr(audit, "_specs_for", _slow_specs)
    monkeypatch.setattr(
        audit,
        "_belt_rules_for",
        lambda url: SimpleNamespace(vertical_construction=False, max_z=1),
    )
    monkeypatch.setitem(
        audit._STRATEGIES,
        "slow",
        lambda workers, vertical, _max_belt_z: _SlowStrategy(),
    )
    monkeypatch.setattr(validate, "id_map", lambda spec: object())
    monkeypatch.setattr(
        validate,
        "validate",
        lambda *args, **kwargs: validate.Report(findings=()),
    )
    job = audit.Job(
        strategy="slow",
        url_id="slow",
        url="test://slow",
        tier="trivial",
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=5.0,
        workers=1,
    )

    result = audit.run_cell(job)

    assert result.status == "CLEAN"
    # The cell took 23.0s; 3.0 of that was building the spec, so the ATTEMPT is
    # 20.0 and the two numbers are deliberately not the same quantity.
    assert result.seconds == pytest.approx(23.0)
    assert result.attempt_wall_s == pytest.approx(20.0)
    # 20.0 - budget(5.0) - ATOMIC_COMPLETION_GRACE_S(5.0) == 10.0, clamped at 0.
    assert result.wall_overshoot_s == pytest.approx(
        20.0 - 5.0 - ATOMIC_COMPLETION_GRACE_S
    )


def test_only_a_row_with_a_placement_carries_a_wall_and_an_overshoot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Gate D2 reports the max overshoot straight off the JSONL, so the keys are
    # present exactly where a placement was measured and ABSENT -- not zero --
    # where none exists: a refusal that never produced a placement overshot
    # nothing, and a zero would be indistinguishable from a punctual cell.
    monkeypatch.setattr(audit, "_JSONL", [])
    job = audit.Job(
        strategy="freeform",
        url_id=URL_CORPUS[0].url_id,
        url=URL_CORPUS[0].url,
        tier=URL_CORPUS[0].tier.value,
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=5.0,
        workers=1,
    )
    tallies = {"freeform": audit.Tally()}

    audit.record(
        tallies,
        audit.Result(
            job,
            "CLEAN",
            "no-proliferator",
            "",
            (),
            12.5,
            attempt_wall_s=12.25,
            wall_overshoot_s=2.25,
        ),
    )
    audit.record(
        tallies,
        audit.Result(job, "REFUSED", "no-proliferator", "refused", ("<refused>",), 3.0),
    )

    placed, refused = audit._JSONL
    assert placed["attempt_wall_s"] == 12.25
    assert placed["wall_overshoot_s"] == 2.25
    assert "attempt_wall_s" not in refused
    assert "wall_overshoot_s" not in refused


def test_a_raced_best_cell_is_judged_by_the_race_grace_not_the_atomic_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `best` runs under `strategy_race.RACE_COMPLETION_GRACE_S` (6.0), a raced
    # child's own completion contract -- not `base.ATOMIC_COMPLETION_GRACE_S`
    # (5.0), which governs a lone serial strategy.  The wall below (20.0) and
    # budget (5.0) are chosen so the two graces disagree by a full, nonzero
    # second (9.0 vs 10.0) rather than both clamping to the same zero, so a
    # `run_cell` that used the wrong grace fails this assertion outright.
    now = [2000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    completed = Placement(
        buildings=(
            PlacedBuilding(item_id=2303, model_index=65, x=0, y=0, width=2, height=3),
        ),
        frame=AreaFrame(2, 3, 4, (4,), False),
        completion=PlacementCompletion.COMPACTED_AND_FINALIZED,
    )

    class _SlowRacingStrategy:
        def lay_out(self, spec: object, *, time_budget_s: float) -> Placement:
            now[0] += 20.0
            return completed

    monkeypatch.setattr(
        audit,
        "_specs_for",
        lambda url, candidate_policies: (SimpleNamespace(label="race grace fixture"),),
    )
    monkeypatch.setattr(
        audit,
        "_belt_rules_for",
        lambda url: SimpleNamespace(vertical_construction=False, max_z=1),
    )
    # Override the real "best" factory: `job.strategy == "best"` is what
    # selects the grace, and only that key does, so the fixture must be
    # installed under "best" itself rather than a fresh strategy name.
    monkeypatch.setitem(
        audit._STRATEGIES,
        "best",
        lambda workers, vertical, _max_belt_z: _SlowRacingStrategy(),
    )
    monkeypatch.setattr(validate, "id_map", lambda spec: object())
    monkeypatch.setattr(
        validate,
        "validate",
        lambda *args, **kwargs: validate.Report(findings=()),
    )
    job = audit.Job(
        strategy="best",
        url_id="race-grace",
        url="test://race-grace",
        tier="trivial",
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=5.0,
        workers=1,
    )

    result = audit.run_cell(job)

    assert result.status == "CLEAN"
    assert result.attempt_wall_s == pytest.approx(20.0)
    # 20.0 - budget(5.0) - RACE_COMPLETION_GRACE_S(6.0) == 9.0.  The ATOMIC
    # form (5.0 grace) would report 10.0 instead: this is the assertion that
    # fails against a `run_cell` that always uses ATOMIC_COMPLETION_GRACE_S.
    assert result.wall_overshoot_s == pytest.approx(20.0 - 5.0 - RACE_COMPLETION_GRACE_S)
    assert result.wall_overshoot_s == pytest.approx(9.0)


def test_the_strategy_flag_accepts_all_five_choices() -> None:
    parser = audit.build_parser()

    for choice in ("both", "all", "freeform", "sequence-pair", "best"):
        args = parser.parse_args(["--strategy", choice])
        assert args.strategy == choice


def test_a_refused_row_carries_the_solver_stats_from_the_exception() -> None:
    audit._JSONL.clear()
    job = audit.Job(
        strategy="sequence-pair",
        url_id=URL_CORPUS[0].url_id,
        url=URL_CORPUS[0].url,
        tier=URL_CORPUS[0].tier.value,
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=1,
    )

    audit.record(
        {"sequence-pair": audit.Tally()},
        audit.Result(
            job,
            "REFUSED",
            "no-proliferator",
            "deadline exhausted",
            ("<refused>",),
            1.0,
            stats={"stages": 11.0, "alns_window_solves": 0.0},
        ),
    )

    assert audit._JSONL[0]["stats"] == {"stages": 11.0, "alns_window_solves": 0.0}


def test_a_row_without_stats_omits_the_key() -> None:
    audit._JSONL.clear()
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

    audit.record({"freeform": audit.Tally()}, audit.Result(job, "CRASH", "?", "", (), 1.0))

    assert "stats" not in audit._JSONL[0]


def test_scalar_stats_drops_list_values_and_keeps_the_scalars() -> None:
    """`PlacementStats.archive_categories` is a `list[str]`; `Result.stats`

    only holds `float | str`.  This is the one conversion site that draws
    that boundary, so it is the one place a `list` value must be provably
    dropped rather than silently reaching a REFUSED/CLEAN/INVALID JSONL row
    Gate E2 (Task 8) is about to read.
    """
    scalars = audit._scalar_stats(
        {
            "archive_categories": ["gear", "circuit-board"],
            "stages": 11,
            "alns_operators": "destroy:failed-endpoints:9",
            "area": 240.5,
        }
    )

    assert scalars == {
        "stages": 11.0,
        "alns_operators": "destroy:failed-endpoints:9",
        "area": 240.5,
    }
