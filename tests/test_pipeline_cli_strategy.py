from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict, Unpack

import pytest

from flab2bp import cli, pipeline
from flab2bp.lab.schema import Dataset


class _BuildKwargs(TypedDict, total=False):
    strategy: pipeline.StrategyName
    power: bool
    candidates: int
    time_budget_s: float
    sequence_islands: int
    dataset: Dataset | None
    name: str
    flow: Path | None
    flow_text: str | None
    fetch_flow: bool
    fetch_timeout_s: float
    browser: str | None
    no_proliferator: bool
    on_progress: pipeline.ProgressSink | None


@pytest.mark.parametrize("strategy", ("spine", "sequence-pair"))
def test_cli_passes_exact_explicit_strategy_name(
    strategy: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received: dict[str, object] = {}

    def fake_build(url: str, **kwargs: Unpack[_BuildKwargs]) -> SimpleNamespace:
        received["url"] = url
        received.update(kwargs)
        return SimpleNamespace(
            blueprint="BLUEPRINT",
            report=SimpleNamespace(errors=()),
        )

    monkeypatch.setattr(pipeline, "build", fake_build)
    monkeypatch.setattr(cli, "_report", lambda build, *, verbose: None)

    assert cli.main(["iron-ingot", "--strategy", strategy, "--no-power"]) == 0
    assert received["strategy"] == strategy
    assert received["power"] is False
    assert capsys.readouterr().out == "BLUEPRINT\n"


@pytest.mark.parametrize(("affinity", "expected"), ((3, 3), (64, 8)))
def test_cli_sequence_pair_uses_affinity_capped_auto_islands(
    monkeypatch: pytest.MonkeyPatch,
    affinity: int,
    expected: int,
) -> None:
    received: dict[str, object] = {}

    def fake_build(url: str, **kwargs: Unpack[_BuildKwargs]) -> SimpleNamespace:
        del url
        received.update(kwargs)
        return SimpleNamespace(
            blueprint="BLUEPRINT",
            report=SimpleNamespace(errors=()),
        )

    monkeypatch.setattr(pipeline, "build", fake_build)
    monkeypatch.setattr(cli, "_report", lambda build, *, verbose: None)
    monkeypatch.setattr(cli, "_available_cpu_count", lambda: affinity)

    assert cli.main(["iron-ingot", "--strategy", "sequence-pair"]) == 0
    assert received["sequence_islands"] == expected


def test_cli_sequence_island_override_accepts_sixteen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    def fake_build(url: str, **kwargs: Unpack[_BuildKwargs]) -> SimpleNamespace:
        del url
        received.update(kwargs)
        return SimpleNamespace(
            blueprint="BLUEPRINT",
            report=SimpleNamespace(errors=()),
        )

    monkeypatch.setattr(pipeline, "build", fake_build)
    monkeypatch.setattr(cli, "_report", lambda build, *, verbose: None)

    assert (
        cli.main(
            [
                "iron-ingot",
                "--strategy",
                "sequence-pair",
                "--sequence-islands",
                "16",
            ]
        )
        == 0
    )
    assert received["sequence_islands"] == 16


@pytest.mark.parametrize(
    "argv",
    (
        ["iron-ingot", "--strategy", "spine", "--sequence-islands", "2"],
        ["iron-ingot", "--strategy", "sequence-pair", "--sequence-islands", "0"],
        ["iron-ingot", "--strategy", "sequence-pair", "--sequence-islands", "17"],
    ),
)
def test_cli_rejects_invalid_sequence_island_use(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    monkeypatch.setattr(
        pipeline,
        "build",
        lambda *args, **kwargs: pytest.fail("invalid CLI arguments reached pipeline"),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main(argv)

    assert exc_info.value.code == 2


def test_strategy_help_separates_best_from_explicit_backends(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    assert exc_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "best temporarily runs only freeform" in help_text
    assert "spine remains available explicitly" in help_text
    assert "sequence-pair remains" in help_text
    assert "experimental/audit backend" in help_text
