from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from flab2bp.layout import finalize
from flab2bp.layout.base import (
    LayoutAttemptFailure,
    NoValidLayout,
    ProjectionFailureRecord,
)
from scripts import audit


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
        lambda url, count: (SimpleNamespace(label="evidence fixture"),),
    )
    monkeypatch.setattr(
        audit,
        "_belt_rules_for",
        lambda url: SimpleNamespace(vertical_construction=False),
    )
    monkeypatch.setitem(
        audit._STRATEGIES,
        "evidence",
        lambda power, workers, vertical: RefusingStrategy(),
    )
    job = audit.Job(
        strategy="evidence",
        url_id="evidence",
        url="test://evidence",
        tier="trivial",
        spec_index=0,
        candidates=1,
        budget=1.0,
        power=False,
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
    placement = object()

    class SuccessfulStrategy:
        def lay_out(self, spec: object, *, time_budget_s: float) -> object:
            return placement

    monkeypatch.setattr(
        audit,
        "_specs_for",
        lambda url, count: (SimpleNamespace(label="projection fixture"),),
    )
    monkeypatch.setattr(
        audit,
        "_belt_rules_for",
        lambda url: SimpleNamespace(vertical_construction=False),
    )
    monkeypatch.setitem(
        audit._STRATEGIES,
        "post-projection",
        lambda power, workers, vertical: SuccessfulStrategy(),
    )
    monkeypatch.setattr(
        audit.finalize,
        "compact_open_boundary_belts",
        lambda result, spec, *, expect_power: result,
    )

    def reject_projection(
        result: object,
        policy: object,
    ) -> object:
        raise refusal

    monkeypatch.setattr(audit.finalize, "finalize_placement", reject_projection)
    monkeypatch.setattr(audit, "_JSONL", [])
    job = audit.Job(
        strategy="post-projection",
        url_id="projection",
        url="test://projection",
        tier="trivial",
        spec_index=0,
        candidates=1,
        budget=1.0,
        power=False,
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
