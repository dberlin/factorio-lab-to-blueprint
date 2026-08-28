"""Fetching a FactorioLab export by driving a headless browser.

Three layers, and only the last needs a browser:

``TestFindBrowser`` / ``TestRefusal``
    That every failure is loud and is a ``FlowError``, so a capture that goes
    wrong refuses the build rather than falling through to a derived recipe
    selection.  That fall-through is the defect this whole feature removes, so
    it is asserted rather than assumed.

``TestWaitConditions``
    The wait logic against a fake page.  This is where the real difficulty
    lives: the page is interactive long before it has an answer, so a capture
    that returns early yields a blueprint for the wrong flow -- which parses
    perfectly and is wrong in exactly the way nothing downstream can detect.

``TestRealCapture``
    A **real export, captured from the live site**, checked in as a fixture.
    Hermetic, because the bytes are on disk.  This is the round trip that had
    never been run when the parser was written: it was built from FactorioLab's
    exporter source, and this is the file that proves the source was read right.

``test_live_capture_round_trip``
    The same thing against the network, gated on ``FLAB2BP_NETWORK_TESTS=1``.
"""

from __future__ import annotations

import asyncio
import json
import os
from fractions import Fraction
from pathlib import Path
from typing import TypedDict

import pytest

from flab2bp.lab.capture import (
    BROWSER_ENV,
    CaptureError,
    SolveProbeState,
    _await_solve,
    capture_flow_csv,
    find_browser,
)
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import (
    FlowError,
    FlowSelection,
    cross_check,
    flow_from_text,
    pin_request,
    unsupplied_inputs,
)
from flab2bp.lab.schema import Dataset
from flab2bp.lab.url import parse_url
from flab2bp.rates.solve import solve

REAL = Path(__file__).parent.parent / "fixtures" / "flow_graphene_real_capture.csv"

#: The URL the checked-in fixture was actually captured from.
REAL_URL = (
    "https://factoriolab.github.io/dsp/list?o=graphene*60&ibe=conveyor-belt-2"
    "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
)


@pytest.fixture(scope="module")
def data() -> Dataset:
    return load_vendored()


class _InvalidSolveProbeState(TypedDict):
    rows: str
    csv: bool


class _FakePage[StateT]:
    """A page whose probe answers from a canned script, one entry per poll."""

    def __init__(self, script: list[StateT]) -> None:
        self.script: list[StateT] = script
        self.calls: int = 0

    async def evaluate(
        self,
        expression: str,
        *,
        await_promise: bool = False,
        return_by_value: bool = False,
    ) -> str:
        state = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return json.dumps(state)


class TestFindBrowser:
    def test_an_explicit_missing_browser_names_itself(self) -> None:
        with pytest.raises(CaptureError, match="does not exist or is not executable"):
            find_browser("/nonexistent/chrome")

    def test_the_env_var_is_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(BROWSER_ENV, "/nonexistent/from-env")
        with pytest.raises(CaptureError, match=BROWSER_ENV):
            find_browser()

    def test_nothing_found_says_what_it_tried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A capture cannot be attempted at all without a browser; say so."""
        monkeypatch.delenv(BROWSER_ENV, raising=False)
        monkeypatch.setattr("flab2bp.lab.capture.shutil.which", lambda _: None)
        monkeypatch.setattr("flab2bp.lab.capture.Path.is_file", lambda _: False)
        with pytest.raises(CaptureError, match="no Chromium or Chrome executable found"):
            find_browser()
        with pytest.raises(CaptureError, match="Tried:"):
            find_browser()


class TestRefusal:
    def test_a_capture_error_is_a_flow_error(self) -> None:
        """So the CLI refuses (exit 2) instead of building something else.

        The load-bearing assertion of this module. If a capture failure were an
        ordinary exception the caller might catch it and carry on with a DERIVED
        recipe selection, silently reintroducing the bug the flow file exists to
        fix.
        """
        assert issubclass(CaptureError, FlowError)
        assert issubclass(CaptureError, ValueError)

    def test_a_missing_browser_refuses_before_any_network(self) -> None:
        with pytest.raises(CaptureError):
            capture_flow_csv(REAL_URL, browser="/nonexistent/chrome", timeout_s=1.0)


class TestWaitConditions:
    """Never a sleep: every wait is on a condition the solve is upstream of."""

    def test_waits_for_the_csv_button_not_merely_for_rows(self) -> None:
        """Rows can exist before the export is available; the button cannot.

        The button is inside `@if (objectivesStore.steps().length)`, so its
        presence *is* the statement that the in-page solver produced steps.
        """
        page = _FakePage[SolveProbeState]([{"rows": 4, "csv": False}] * 3)
        with pytest.raises(CaptureError, match="did not finish solving"):
            asyncio.run(_await_solve(page, REAL_URL, deadline_s=0.9))
        assert page.calls >= 2, "should have polled repeatedly, not slept once"

    def test_requires_the_row_count_to_settle(self) -> None:
        """A count still moving is a table still being built.

        The first poll showing a button and rows is not enough -- it must agree
        with the next one, or we could read a half-built flow and silently drop
        steps from the blueprint.
        """
        page = _FakePage[SolveProbeState](
            [
                {"rows": 1, "csv": True},
                {"rows": 3, "csv": True},
                {"rows": 4, "csv": True},
                {"rows": 4, "csv": True},
            ]
        )
        asyncio.run(_await_solve(page, REAL_URL, deadline_s=5.0))
        assert page.calls >= 4, "returned before the count repeated"

    def test_an_empty_page_times_out_naming_what_it_awaited(self) -> None:
        page = _FakePage[SolveProbeState]([{"rows": 0, "csv": False}])
        with pytest.raises(CaptureError) as exc:
            asyncio.run(_await_solve(page, REAL_URL, deadline_s=0.6))
        message = str(exc.value)
        assert "CSV button absent" in message
        assert "0 step row(s)" in message
        assert REAL_URL in message

    def test_invalid_probe_payload_refuses_at_the_browser_boundary(self) -> None:
        page = _FakePage[_InvalidSolveProbeState](
            [_InvalidSolveProbeState(rows="four", csv=True)]
        )
        with pytest.raises(CaptureError, match="invalid solve probe"):
            asyncio.run(_await_solve(page, REAL_URL, deadline_s=0.6))


@pytest.fixture(scope="module")
def flow() -> FlowSelection:
    """The checked-in real export, through the same door a user's file uses."""
    return flow_from_text(REAL.read_text(), url=REAL_URL)


class TestRealCapture:
    """A genuine download, checked in. The round trip the parser never had."""

    def test_it_parses_and_provenance_holds(self, flow: FlowSelection) -> None:
        """`flow_from_text` verifies line 1 against the URL we drove to."""
        assert flow.source_url == REAL_URL

    def test_a_real_export_is_exact(self, flow: FlowSelection) -> None:
        """The finding that chose CSV over JSON, confirmed on a real file.

        `=1/12` is in the bytes on disk. The nine-place decimals in the sample
        that motivated calling the CSV lossy were a spreadsheet evaluating
        `=p/q` formulas, not the exporter.
        """
        assert flow.is_exact
        assert "=1/12" in REAL.read_text()
        assert flow.by_item["graphene"].machines == Fraction(3, 2)
        assert flow.by_item["coal"].items == Fraction(180)

    def test_the_header_is_dynamic(self, flow: FlowSelection) -> None:
        """Only columns some row fills are emitted -- no `Surplus` here.

        Pinned because it is why columns must be read by name, never position.
        """
        assert "Surplus" not in flow.columns
        assert "Machines" in flow.columns and "Recipe" in flow.columns

    def test_modules_can_be_a_count_with_no_module(self, flow: FlowSelection) -> None:
        """The real file writes `"1 "` -- a count and an EMPTY module id.

        Two consequences, both found here rather than reasoned about. Parsing
        `Modules` into `<count> <id>` pairs would have REFUSED this valid file;
        and testing "is the cell non-empty" to detect proliferation would read
        this unproliferated flow as proliferated.
        """
        assert flow.by_item["graphene"].modules == "1"
        assert not flow.uses_proliferator

    def test_it_reproduces_the_stone_bug_and_the_fix(
        self, data: Dataset, flow: FlowSelection
    ) -> None:
        """The motivating defect, on a real export of a real corpus URL.

        FactorioLab belts sulfuric acid in (`sulphuric-acid-vein`, a mining
        recipe). Our unpinned solve instead BUILDS it, which drags in stone,
        water and crude oil -- inputs the player's flow does not contain. That
        is the reported bug, and pinning removes it.
        """
        derived = solve(data, parse_url(REAL_URL))
        assert {"stone", "water", "crude-oil"} <= set(derived.external_inputs)

        pinned = solve(data, pin_request(parse_url(REAL_URL), data, flow))
        assert dict(pinned.external_inputs) == {
            "coal": Fraction(3),
            "sulfuric-acid": Fraction(1, 2),
        }
        assert unsupplied_inputs(flow, data, pinned.external_inputs) == ()

    def test_the_exact_cross_check_agrees(
        self, data: Dataset, flow: FlowSelection
    ) -> None:
        """Both sides exact rationals, and they match -- machines and rates.

        This is the check the JSON export could not support at all.
        """
        plan = solve(data, pin_request(parse_url(REAL_URL), data, flow))
        assert cross_check(
            flow,
            data,
            machines={g.recipe_id: g.machines for g in plan.groups},
            machine_items={g.recipe_id: g.machine_item_id for g in plan.groups},
            external_inputs=plan.external_inputs,
            outputs=dict(plan.outputs),
        ) == ()


# --------------------------------------------------------------------------
# Network + browser (deselected by default)
# --------------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.skipif(
    not os.environ.get("FLAB2BP_NETWORK_TESTS"),
    reason="set FLAB2BP_NETWORK_TESTS=1 to drive a real browser at factoriolab.github.io",
)
def test_live_capture_round_trip(data: Dataset) -> None:
    """Drive the real site and put the result through the whole pipe."""
    flow = flow_from_text(capture_flow_csv(REAL_URL, timeout_s=120.0), url=REAL_URL)
    assert flow.is_exact
    assert flow.chosen_recipe_ids
    plan = solve(data, pin_request(parse_url(REAL_URL), data, flow))
    assert unsupplied_inputs(flow, data, plan.external_inputs) == ()
    assert cross_check(
        flow,
        data,
        machines={g.recipe_id: g.machines for g in plan.groups},
        machine_items={g.recipe_id: g.machine_item_id for g in plan.groups},
        external_inputs=plan.external_inputs,
        outputs=dict(plan.outputs),
    ) == ()
