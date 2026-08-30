from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

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
