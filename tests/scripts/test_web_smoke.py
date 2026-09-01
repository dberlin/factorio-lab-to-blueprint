from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import NoReturn, cast

import pytest

from flab2bp.rates import CandidatePolicy
from scripts import web_smoke


def test_drive_sets_the_exact_named_candidate_policy_subset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operations: list[tuple[str, str]] = []

    async def fake_expect_ok(
        page: web_smoke._Page,
        script: str,
        what: str,
    ) -> None:
        del page
        operations.append((what, script))

    async def fake_settle(
        page: web_smoke._Page,
        out: Path,
        tag: str,
    ) -> web_smoke.PageState:
        del page, out, tag
        return cast(web_smoke.PageState, {})

    monkeypatch.setattr(web_smoke, "_expect_ok", fake_expect_ok)
    monkeypatch.setattr(web_smoke, "_settle", fake_settle)

    asyncio.run(
        web_smoke._drive(
            cast(web_smoke._Page, object()),
            url="https://example.invalid",
            strategy="freeform",
            candidate_policies=(
                CandidatePolicy.NO_PROLIFERATOR,
                CandidatePolicy.OUTPUT_PRODUCTS,
            ),
            budget_s=4.0,
            out=tmp_path,
            tag="test",
        )
    )

    policy_operations = [
        operation
        for operation in operations
        if operation[0] == "setting candidate policies"
    ]
    assert len(policy_operations) == 1
    assert policy_operations[0][1].rstrip().endswith(
        ")(" + json.dumps(["no-proliferator", "output-products"]) + ")"
    )


def test_web_smoke_scenarios_keep_their_intended_named_policy_subsets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    received: list[tuple[CandidatePolicy, ...]] = []

    async def stop_drive(*args: object, **kwargs: object) -> NoReturn:
        del args
        received.append(cast(tuple[CandidatePolicy, ...], kwargs["candidate_policies"]))
        raise _StopDrive

    class _StopDrive(Exception):
        pass

    monkeypatch.setattr(web_smoke, "_drive", stop_drive)
    page = cast(web_smoke._Page, object())
    cdp = cast(web_smoke._Cdp, object())

    async def run_cases() -> None:
        with pytest.raises(_StopDrive):
            await web_smoke._case_success(page, cdp, tmp_path)
        with pytest.raises(_StopDrive):
            await web_smoke._case_refusal(page, cdp, tmp_path)
        with pytest.raises(_StopDrive):
            await web_smoke._case_flow_pin(page, tmp_path)

    asyncio.run(run_cases())

    assert received == [
        (
            CandidatePolicy.NO_PROLIFERATOR,
            CandidatePolicy.ALL_PRODUCTS,
            CandidatePolicy.OUTPUT_PRODUCTS,
        ),
        (CandidatePolicy.NO_PROLIFERATOR,),
        (CandidatePolicy.NO_PROLIFERATOR,),
    ]
