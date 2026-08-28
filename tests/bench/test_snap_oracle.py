from __future__ import annotations

import json
import subprocess

import pytest
from pydantic import ValidationError

from flab2bp.bench import snaporacle


def _case() -> snaporacle.Case:
    return snaporacle.Case(name="typed", lpos=(0.0, 0.0, 0.0), lpos2=(1.0, 0.0, 0.0))


def _returning(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    def run(
        args: list[str], _stdin: str, _timeout_s: float
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(snaporacle, "_run", run)


def test_ask_validates_subprocess_verdicts(monkeypatch: pytest.MonkeyPatch) -> None:
    _returning(monkeypatch, [{"name": "typed", "inputObjId": "not-an-integer"}])

    with pytest.raises(ValidationError, match="inputObjId"):
        _ = snaporacle.ask([_case()])


def test_ask_accepts_future_wire_fields_and_preserves_score_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = {
        "index": 0,
        "num8": 1.25,
        "num9": 2,
        "num10": 3,
        "flag5": True,
        "future": {"nested": [1, "two"]},
    }
    _returning(
        monkeypatch,
        [
            {
                "name": "typed",
                "futureVerdictField": 7,
                "trace": [
                    {
                        "side": "input",
                        "num4": 1.0,
                        "num5": 2,
                        "num6": 3,
                        "preview": -1,
                        "flag4": False,
                        "flag3": True,
                        "scores": [score],
                        "futureStepField": False,
                    }
                ],
            }
        ],
    )

    verdict = snaporacle.ask([_case()])[0]

    assert verdict.name == "typed"
    assert verdict.trace[0].scores == (score,)


def test_selftest_validates_failure_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    _returning(monkeypatch, {"ok": False, "failures": [1]})

    with pytest.raises(ValidationError, match="failures"):
        _ = snaporacle.selftest()
