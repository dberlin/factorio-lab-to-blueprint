from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from flab2bp import cli, pipeline
from flab2bp.layout.sequence_solver import SequencePairLayout


def test_explicit_sequence_pair_selects_only_sequence_pair() -> None:
    assert pipeline._strategy_names("sequence-pair") == ("sequence-pair",)


def test_best_selects_only_production_backends() -> None:
    assert pipeline._strategy_names("best") == ("spine", "freeform")


def test_sequence_pair_constructs_sequence_pair_layout() -> None:
    layout = pipeline._new_layout(
        "sequence-pair", power=True, belt_vertical_construction=True
    )

    assert isinstance(layout, SequencePairLayout)
    assert layout.power is True


def test_cli_passes_exact_sequence_pair_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    received: dict[str, Any] = {}

    def fake_build(url: str, **kwargs: Any) -> SimpleNamespace:
        received["url"] = url
        received.update(kwargs)
        return SimpleNamespace(
            blueprint="BLUEPRINT",
            report=SimpleNamespace(errors=()),
        )

    monkeypatch.setattr(pipeline, "build", fake_build)
    monkeypatch.setattr(cli, "_report", lambda build, *, verbose: None)

    assert cli.main(["iron-ingot", "--strategy", "sequence-pair", "--no-power"]) == 0
    assert received["strategy"] == "sequence-pair"
    assert received["power"] is False
    assert capsys.readouterr().out == "BLUEPRINT\n"


def test_strategy_help_separates_best_from_experimental_backend(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    assert exc_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "best evaluates only spine and freeform" in help_text
    assert "sequence-pair is an explicit experimental/audit backend" in help_text
