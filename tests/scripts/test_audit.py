from __future__ import annotations

import json
import subprocess
import time
from types import SimpleNamespace

import pytest

from flab2bp.bench.corpus import URL_CORPUS, Tier
from flab2bp.layout import finalize, route_kernel, validate
from flab2bp.layout.base import (
    ATOMIC_COMPLETION_GRACE_S,
    AreaFrame,
    PlacedBuilding,
    Placement,
    PlacementCompletion,
)
from flab2bp.layout.strategy_race import RACE_COMPLETION_GRACE_S
from flab2bp.rates import CandidatePolicy
from scripts import audit


def test_audit_spec_cache_does_not_mix_power_choices() -> None:
    policies = (CandidatePolicy.NO_PROLIFERATOR,)
    url = "https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11"
    tesla = audit._specs_for(url, policies, power_tower="tesla")
    substation = audit._specs_for(url, policies, power_tower="substation")
    assert {spec.power_tower_item_id for spec in tesla} == {"tesla-tower"}
    assert {spec.power_tower_item_id for spec in substation} == {"satellite-substation"}


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
        lambda url, candidate_policies, machine_rank, power_tower: (
            SimpleNamespace(label="projection fixture"),
        ),
    )
    monkeypatch.setattr(
        audit,
        "_belt_rules_for",
        lambda url: SimpleNamespace(vertical_construction=False, max_z=1),
    )
    monkeypatch.setitem(
        audit._STRATEGIES,
        "post-projection",
        lambda workers, rules: SuccessfulStrategy(),
    )

    def compact_stub(
        result: object, spec: object, *, expect_power: bool, belt_rules: object
    ) -> object:
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

    result = audit.run_cell(job, belt_rules=audit._belt_rules_for(job.url))
    audit.record({"post-projection": audit.Tally()}, result)
    persisted = json.loads(json.dumps(audit._JSONL[-1]))

    assert result.status == "REFUSED"
    # The attempt ran 500.0 -> 507.0 (compact +4.0, then the projection refusal
    # +3.0) = 7.0s wall; 7.0 - budget(1.0) - ATOMIC_COMPLETION_GRACE_S(5.0) ==
    # 1.0, clamped at 0.  A refusal AFTER a placement existed is not the same
    # as a refusal that never built one: this row is honest carrying both.
    assert result.attempt_wall_s == pytest.approx(7.0)
    assert result.wall_overshoot_s == pytest.approx(1.0)
    assert persisted["attempt_wall_s"] == pytest.approx(7.0)
    assert persisted["wall_overshoot_s"] == pytest.approx(1.0)


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


def test_all_includes_native_transport_and_the_portfolio() -> None:
    assert audit.strategy_names("all") == ("freeform", "sequence-pair", "transport-routing", "best")
    assert audit.strategy_names("both") == ("freeform", "sequence-pair")


def test_a_full_all_strategy_run_covers_every_policy_and_strategy() -> None:
    jobs = audit.build_jobs(
        list(audit.strategy_names("all")),
        set(Tier),
        [30.0],
        8,
    )

    # 12 corpus URLs x 3 candidate policies x 4 strategies.
    assert len(jobs) == 144
    assert {job.strategy for job in jobs} == {
        "freeform",
        "sequence-pair",
        "transport-routing",
        "best",
    }


def test_a_clean_cell_reports_its_attempt_wall_and_the_overshoot_past_the_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Driven clock, no sleeping: `now[0]` is the only time source `run_cell`
    # sees, and the stub strategy advances it by exactly the wall under test.
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    completed = Placement(
        buildings=(PlacedBuilding(item_id=2303, model_index=65, x=0, y=0, width=2, height=3),),
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
        machine_rank: object,
        power_tower: str | None,
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
        lambda workers, rules: _SlowStrategy(),
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

    result = audit.run_cell(job, belt_rules=audit._belt_rules_for(job.url))

    assert result.status == "CLEAN"
    # The cell took 23.0s; 3.0 of that was building the spec, so the ATTEMPT is
    # 20.0 and the two numbers are deliberately not the same quantity.
    assert result.seconds == pytest.approx(23.0)
    assert result.attempt_wall_s == pytest.approx(20.0)
    # 20.0 - budget(5.0) - ATOMIC_COMPLETION_GRACE_S(5.0) == 10.0, clamped at 0.
    assert result.wall_overshoot_s == pytest.approx(20.0 - 5.0 - ATOMIC_COMPLETION_GRACE_S)


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
        buildings=(PlacedBuilding(item_id=2303, model_index=65, x=0, y=0, width=2, height=3),),
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
        lambda url, candidate_policies, machine_rank, power_tower: (
            SimpleNamespace(label="race grace fixture"),
        ),
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
        lambda workers, rules: _SlowRacingStrategy(),
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

    result = audit.run_cell(job, belt_rules=audit._belt_rules_for(job.url))

    assert result.status == "CLEAN"
    assert result.attempt_wall_s == pytest.approx(20.0)
    # 20.0 - budget(5.0) - RACE_COMPLETION_GRACE_S(6.0) == 9.0.  The ATOMIC
    # form (5.0 grace) would report 10.0 instead: this is the assertion that
    # fails against a `run_cell` that always uses ATOMIC_COMPLETION_GRACE_S.
    assert result.wall_overshoot_s == pytest.approx(20.0 - 5.0 - RACE_COMPLETION_GRACE_S)
    assert result.wall_overshoot_s == pytest.approx(9.0)


def test_the_strategy_flag_accepts_every_audit_choice() -> None:
    parser = audit.build_parser()

    for choice in ("both", "all", "freeform", "sequence-pair", "transport-routing", "best"):
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
