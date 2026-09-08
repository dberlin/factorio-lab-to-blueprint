"""Evidence from distinct revisions must never be compared as machine-rank arms."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

EVIDENCE = (
    Path(__file__).resolve().parents[2]
    / "docs/superpowers/evidence/2026-09-07-machine-upto"
)
SHA_A = "a" * 40
SHA_B = "b" * 40


@pytest.fixture
def gate_modules(monkeypatch):
    modules = []
    for name in ("run_gate", "moved"):
        spec = importlib.util.spec_from_file_location(name, EVIDENCE / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


@pytest.mark.parametrize(
    ("old_mode", "old_arm", "new_mode", "new_arm"),
    [
        ("round", "exact", "round", "up-to"),
        ("controls", "exact", "round", "exact"),
        ("round", "up-to", "reported", "exact"),
    ],
)
@pytest.mark.parametrize("shared_identity", [False, True])
def test_gate_refuses_other_candidate_revision_before_launch(
    gate_modules, monkeypatch, tmp_path, old_mode, old_arm, new_mode, new_arm, shared_identity
):
    gate, _ = gate_modules
    root = tmp_path / "checkout"
    root.mkdir()
    out = tmp_path / "evidence"
    out.mkdir()
    imported = str(root / "src/flab2bp/__init__.py")
    identity = {"commit": SHA_A, "checkout": str(root), "imported": imported}
    previous = {**identity, "mode": old_mode, "arm": old_arm}
    (out / f"{old_mode}-{old_arm}-provenance.json").write_text(json.dumps(previous))
    if shared_identity:
        (out / "candidate-provenance.json").write_text(json.dumps(identity))

    def check_output(command, **kwargs):
        return SHA_B if command[0] == "git" else imported

    def no_launch(*args, **kwargs):
        pytest.fail("a mixed-revision gate must stop before pressure sampling or launch")

    monkeypatch.setattr(gate.subprocess, "check_output", check_output)
    monkeypatch.setattr(gate, "pressure", no_launch)
    monkeypatch.setattr(gate.subprocess, "run", no_launch)
    monkeypatch.setattr(
        sys, "argv", ["run_gate", new_mode, new_arm, str(root), "--out", str(out)]
    )
    with pytest.raises(RuntimeError, match="candidate provenance"):
        gate.main()
    assert not (out / f"{new_mode}-{new_arm}-provenance.json").exists()
    assert json.loads((out / f"{old_mode}-{old_arm}-provenance.json").read_text()) == previous


def _layouts(directory, gate, *, exact_sha=SHA_A, upto_sha=SHA_A):
    identity = {"commit": SHA_A, "checkout": "/candidate", "imported": "/candidate/src/flab2bp"}
    (directory / "candidate-provenance.json").write_text(json.dumps(identity))
    for arm, commit in (("base", gate.BASE_SHA + "0" * 32), ("exact", exact_sha), ("up-to", upto_sha)):
        rows = [
            {"strategy": strategy, "url_id": url_id, "spec_index": index,
             "commit": commit, "machine_rank": arm, "status": "REFUSED"}
            for strategy in gate.STRATEGIES for url_id in gate.URL_IDS for index in range(3)
        ]
        (directory / f"{arm}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows)
        )


@pytest.mark.parametrize("mismatch", ["exact", "up-to", "rates"])
def test_moved_refuses_stale_layouts_before_rates_or_table(
    gate_modules, monkeypatch, tmp_path, capsys, mismatch
):
    gate, moved = gate_modules
    _layouts(
        tmp_path, gate,
        exact_sha=SHA_B if mismatch == "exact" else SHA_A,
        upto_sha=SHA_B if mismatch == "up-to" else SHA_A,
    )
    monkeypatch.setattr(
        moved.subprocess, "check_output",
        lambda *args, **kwargs: SHA_B if mismatch == "rates" else SHA_A,
    )

    def no_rates():
        pytest.fail("stale layouts must be rejected before computing any rates")

    monkeypatch.setattr(moved, "load_vendored", no_rates)
    output = tmp_path / "moved.jsonl"
    monkeypatch.setattr(
        sys, "argv", ["moved", "--out", str(output), "--layouts", str(tmp_path)]
    )
    with pytest.raises(RuntimeError, match="rates measurement SHA"):
        moved.main()
    assert not output.exists()
    assert capsys.readouterr().out == ""


def test_matching_candidate_layouts_accept_distinct_pinned_baseline(gate_modules, tmp_path):
    gate, moved = gate_modules
    _layouts(tmp_path, gate)
    layouts = moved.load_layouts(tmp_path, SHA_A)
    assert set(layouts) == {"base", "exact", "up-to"}
    expected = {(strategy, url_id, index) for strategy in gate.STRATEGIES
                for url_id in gate.URL_IDS for index in range(3)}
    assert all(set(arm) == expected for arm in layouts.values())
