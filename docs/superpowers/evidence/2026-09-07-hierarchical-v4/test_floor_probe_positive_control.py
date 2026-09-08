"""Positive control for `floor_probe.py` (Task 6 fix round 1, Finding 4).

The real 25-cell sweep and 18-run deadline grid are NOT re-run here -- both
are valid and both derived numbers stand; this file does not touch them.

Nothing in the real sweep ever succeeded (all 25 cells refused), so
`floor_probe.main`'s SUCCESS branch was never exercised by any evidence this
task produced -- which is exactly how Finding 3 (`Placement.area` exists,
base.py:555-561, and the probe was not using it) went unnoticed: the one
branch that was wrong was also the one branch nothing had run. This module
drives BOTH branches of `floor_probe.main` with every collaborator it calls
(`build_candidates`, `belt_rules_for_url`, `initial_partition`, `sub_spec`,
and `SequencePairLayout.lay_out`) stubbed out, so it is fast, hermetic, and
proves the SUCCESS branch reports exactly what `Placement.area` computes --
not a hand-rolled `frame.width * frame.height` -- while the refusal branch is
kept alongside it so one file covers `main`'s only two outcomes.

`floor_probe.py` is a standalone script (evidence, not part of the `flab2bp`
package), so it is loaded here by file path via `importlib.util` rather than
imported normally.
"""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path

import pytest

from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import AreaFrame, NoValidLayout, PlacedBuilding, Placement

_MODULE_PATH = Path(__file__).with_name("floor_probe.py")


def _load_floor_probe() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("floor_probe_under_test", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeUnit:
    def __init__(self, recipe: str) -> None:
        self.recipe = recipe


class _FakeCandidates:
    def __init__(self, spec: object) -> None:
        self.candidates = [spec]


class _FakePartition:
    def __init__(self, blocks: list[list[object]]) -> None:
        self.blocks = blocks


class _FakeBeltRules:
    vertical_construction = True


def _stub_collaborators(
    floor_probe: types.ModuleType, monkeypatch: pytest.MonkeyPatch, block: list[object]
) -> None:
    monkeypatch.setattr(floor_probe, "parse_url", lambda url: object())
    monkeypatch.setattr(floor_probe, "load_vendored", lambda: object())
    monkeypatch.setattr(floor_probe, "build_candidates", lambda *a, **k: _FakeCandidates(object()))
    monkeypatch.setattr(floor_probe, "belt_rules_for_url", lambda url: _FakeBeltRules())
    monkeypatch.setattr(
        floor_probe, "initial_partition", lambda spec, **k: _FakePartition([block])
    )
    monkeypatch.setattr(floor_probe, "sub_spec", lambda spec, blk, index: object())


def test_floor_probe_reports_an_exact_layout_when_the_arm_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    floor_probe = _load_floor_probe()
    _stub_collaborators(floor_probe, monkeypatch, [_FakeUnit("widget"), _FakeUnit("widget")])

    stub_placement = Placement(
        buildings=(PlacedBuilding(item_id=1, model_index=1, x=0, y=0, width=3, height=2),),
        frame=AreaFrame(
            width=10, height=8, primary_band=100, certified_bands=(100,), rotated=False
        ),
    )

    def _stub_lay_out(
        self: object, spec: object, *, time_budget_s: float, absolute_deadline: float | None = None
    ) -> Placement:
        assert self.band_policy == BandPolicy.parse("portable")  # type: ignore[attr-defined]
        # `SequencePairLayout.__init__` stores `ramped = not
        # belt_vertical_construction`, not the flag itself (sequence_solver.py
        # :6382); `ramped is False` here confirms `belt_vertical_construction`
        # was passed as `True`, the value `belt_rules_for_url` derives for the
        # stubbed URL via `_FakeBeltRules`.
        assert self.ramped is False  # type: ignore[attr-defined]
        assert self.islands == 1  # type: ignore[attr-defined]
        assert time_budget_s == 12.5
        return stub_placement

    monkeypatch.setattr(floor_probe.SequencePairLayout, "lay_out", _stub_lay_out)

    out = tmp_path / "control.json"
    exit_code = floor_probe.main(
        [str(out), "https://example.invalid/", "NO_PROLIFERATOR", "0", "12.5"]
    )

    assert exit_code == 0
    record = json.loads(out.read_text())
    assert record["ok"] is True
    assert record["block"] == 0
    assert record["budget_s"] == 12.5
    assert record["recipes"] == ["widget"]
    assert record["frame"] == {"width": 10, "height": 8}
    # `Placement.area` (base.py:555-561), not `frame.width * frame.height`
    # computed by hand: this is the assertion Finding 3's fix protects. Both
    # give 80 here (frame is set), but only `.area` also covers the
    # `frame is None` fallback to building-bounds area, which the hand-rolled
    # version could not.
    assert record["area"] == 80
    assert isinstance(record["wall_s"], float)


def test_floor_probe_reports_a_refusal_when_the_arm_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The branch the real sweep exercised 25 times out of 25 -- kept here so
    `main`'s only two outcomes are both covered by this one file."""
    floor_probe = _load_floor_probe()
    _stub_collaborators(floor_probe, monkeypatch, [_FakeUnit("magnet")])

    def _stub_lay_out(
        self: object, spec: object, *, time_budget_s: float, absolute_deadline: float | None = None
    ) -> Placement:
        raise NoValidLayout(
            "no valid layout for no-proliferator#block0 after 5s: "
            "deadline exhausted before finding an exact layout"
        )

    monkeypatch.setattr(floor_probe.SequencePairLayout, "lay_out", _stub_lay_out)

    out = tmp_path / "control.json"
    exit_code = floor_probe.main(
        [str(out), "https://example.invalid/", "NO_PROLIFERATOR", "0", "5.0"]
    )

    assert exit_code == 0
    record = json.loads(out.read_text())
    assert record["ok"] is False
    assert record["recipes"] == ["magnet"]
    assert "deadline exhausted" in record["verdict"]
