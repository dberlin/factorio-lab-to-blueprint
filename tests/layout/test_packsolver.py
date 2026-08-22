"""Tests for the PackingSolver experiment.

Everything needing the external binary is marked ``packsolver`` and skipped when
it is absent, so this suite never makes an optional C++ build a prerequisite for
running the project's tests.
"""

from __future__ import annotations

import csv
from fractions import Fraction as F
from pathlib import Path

import pytest

from flab2bp.layout import validate
from flab2bp.layout.freeform import MARGIN, plan_strips
from flab2bp.layout.packsolver import (
    CONCLUSION,
    PackSolverLayout,
    _read_certificate,
    _write_instance,
    is_available,
)
from flab2bp.spec import BuildSpec, MachineGroup

needs_binary = pytest.mark.skipif(
    not is_available(), reason="packingsolver_rectangle not built"
)


def two_stage_spec() -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=4,
                inputs_per_machine={"iron-ore": F(1)},
                outputs_per_machine={"iron-ingot": F(1)},
            ),
            MachineGroup(
                recipe_id="gear",
                machine_item_id="assembling-machine-2",
                count=2,
                inputs_per_machine={"iron-ingot": F(1)},
                outputs_per_machine={"gear": F(1)},
            ),
        ),
        external_inputs={"iron-ore": F(4)},
        outputs={"gear": F(2)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="two-stage",
    )


# --- certificate parsing (no binary needed) --------------------------------


def _certificate(tmp_path: Path, rows: list[list[object]]) -> Path:
    path = tmp_path / "solution.csv"
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["TYPE", "ID", "COPIES", "BIN", "X", "Y", "LX", "LY", "GROUP_ID"])
        for r in rows:
            w.writerow(r)
    return path


class TestCertificateParsing:
    def test_the_bin_row_does_not_claim_an_items_origin(self, tmp_path: Path) -> None:
        """The first certificate row is the BIN, not an item.

        Without a TYPE filter it has ID 0, X 0, Y 0 and silently becomes strip
        0's origin -- which reads as a suspiciously good pack rather than as a
        parse error.
        """
        strips = plan_strips(two_stage_spec(), strip_len=6)
        assert len(strips) >= 2
        rows: list[list[object]] = [["BIN", 0, 1, 0, 0, 0, 100, 10, ""]]
        for i, s in enumerate(strips):
            rows.append(
                ["ITEM", i, 1, 0, 7 + i, 3 + i, s.width + MARGIN, s.height + MARGIN, 0]
            )
        at = _read_certificate(_certificate(tmp_path, rows), strips)
        assert at is not None
        # Strip 0's origin is its ITEM row, not the bin's (0, 0).
        assert at[0] == (7, 3)

    def test_a_rotated_item_is_rejected_rather_than_placed(self, tmp_path: Path) -> None:
        """A strip's lanes sit above and below its machine row.

        Rotating it puts them beside the machines, out of sorter reach: wrong
        geometry, not merely a different shape.
        """
        strips = plan_strips(two_stage_spec(), strip_len=6)
        rows: list[list[object]] = [["BIN", 0, 1, 0, 0, 0, 100, 10, ""]]
        for i, s in enumerate(strips):
            w, h = s.width + MARGIN, s.height + MARGIN
            swap = i == 0  # rotate exactly one
            rows.append(["ITEM", i, 1, 0, 0, 0, h if swap else w, w if swap else h, 0])
        assert _read_certificate(_certificate(tmp_path, rows), strips) is None

    def test_a_short_certificate_is_rejected(self, tmp_path: Path) -> None:
        """Missing an item means no usable pack; never guess the remainder."""
        strips = plan_strips(two_stage_spec(), strip_len=6)
        rows: list[list[object]] = [["BIN", 0, 1, 0, 0, 0, 100, 10, ""]]
        s = strips[0]
        rows.append(["ITEM", 0, 1, 0, 0, 0, s.width + MARGIN, s.height + MARGIN, 0])
        assert _read_certificate(_certificate(tmp_path, rows), strips) is None

    def test_written_instance_round_trips_every_strip(self, tmp_path: Path) -> None:
        strips = plan_strips(two_stage_spec(), strip_len=6)
        items, bins = _write_instance(tmp_path, strips, height=20, width_bound=60)
        with items.open() as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == len(strips)
        assert [int(r["WIDTH"]) for r in rows] == [s.width + MARGIN for s in strips]
        with bins.open() as fh:
            assert list(csv.DictReader(fh))[0]["HEIGHT"] == "20"


# --- behaviour without the binary ------------------------------------------


def test_falls_back_rather_than_raising_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unbuilt optional dependency must degrade, not explode."""
    monkeypatch.setattr("flab2bp.layout.packsolver.is_available", lambda: False)
    p = PackSolverLayout(power=False).lay_out(two_stage_spec(), time_budget_s=1.0)
    assert p.buildings


def test_zero_budget_returns_the_fallback() -> None:
    p = PackSolverLayout(power=False).lay_out(two_stage_spec(), time_budget_s=0.0)
    assert p.buildings


def test_conclusion_records_the_measured_verdict() -> None:
    """The finding lives in code, so it cannot quietly rot into folklore."""
    assert "REJECTED" in CONCLUSION
    assert "1.127" in CONCLUSION


# --- with the binary --------------------------------------------------------


@needs_binary
def test_produces_a_valid_placement() -> None:
    spec = two_stage_spec()
    p = PackSolverLayout(power=False).lay_out(spec, time_budget_s=2.0)
    assert p.stats.get("fallback_used", 0.0) == 0.0
    report = validate.validate(p, expect_power=False)
    assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:5])


@needs_binary
def test_machines_do_not_overlap() -> None:
    """The certificate is parsed by hand, so prove the origins are usable."""
    from flab2bp.dsp import catalog

    p = PackSolverLayout(power=False).lay_out(two_stage_spec(), time_budget_s=2.0)
    seen: set[tuple[int, int, int]] = set()
    for b in p.buildings:
        if catalog.is_belt_integrated(b.item_id):
            continue
        if not catalog.building(b.item_id).occupies_tiles:
            continue
        for cell in b.tiles():
            assert cell not in seen, f"two buildings on {cell}"
            seen.add(cell)
