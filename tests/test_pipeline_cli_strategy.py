from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict, Unpack

import pytest

from flab2bp import cli, pipeline
from flab2bp.lab.schema import Dataset
from flab2bp.layout.band_policy import BAND_SELECTIONS, BandSelection
from flab2bp.layout.base import (
    AreaFrame,
    LayoutAttemptFailure,
    NoValidLayout,
    ProjectionFailureRecord,
)


class _BuildKwargs(TypedDict, total=False):
    strategy: pipeline.StrategyName
    band: BandSelection
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


@pytest.fixture(scope="module")
def band_build() -> pipeline.Build:
    return pipeline.build(
        "https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11",
        strategy="freeform",
        candidates=1,
        time_budget_s=3.0,
    )


@pytest.mark.parametrize("strategy", ("freeform", "sequence-pair"))
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

    assert cli.main(["iron-ingot", "--strategy", strategy]) == 0
    assert received["strategy"] == strategy
    assert "power" not in received
    assert received["time_budget_s"] == 15.0
    assert capsys.readouterr().out == "BLUEPRINT\n"
    assert received["band"] == "portable"


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
        ["iron-ingot", "--strategy", "freeform", "--sequence-islands", "2"],
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
    assert "best runs freeform and sequence-pair" in help_text
    assert "smallest fitting band plus up to two wider bands" in help_text
    assert "--no-power" not in help_text


def test_cli_rejects_removed_no_power_option(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        pipeline,
        "build",
        lambda *args, **kwargs: pytest.fail("legacy CLI option reached pipeline"),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["iron-ingot", "--no-power"])

    assert exc_info.value.code == 2
    assert "--no-power" in capsys.readouterr().err

def test_cli_band_choices_are_exact_and_reach_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[object] = []

    def fake_build(url: str, **kwargs: Unpack[_BuildKwargs]) -> SimpleNamespace:
        del url
        received.append(kwargs["band"])
        return SimpleNamespace(
            blueprint="BLUEPRINT",
            report=SimpleNamespace(errors=()),
        )

    monkeypatch.setattr(pipeline, "build", fake_build)
    monkeypatch.setattr(cli, "_report", lambda build, *, verbose: None)

    for selection in BAND_SELECTIONS:
        assert cli.main(["iron-ingot", "--band", selection]) == 0
    assert tuple(received) == BAND_SELECTIONS
    assert cli.main(["iron-ingot", "--band", "160"]) == 0
    assert received[-1] == "50x800"


    with pytest.raises(SystemExit) as exc_info:
        cli.main(["iron-ingot", "--band", "240"])
    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "certified",
    (
        (160,),
        (160, 200),
        (120, 160, 200),
    ),
)
def test_cli_reports_literal_band_evidence(
    certified: tuple[int, ...],
    band_build: pipeline.Build,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_frame = band_build.placement.frame
    assert original_frame is not None
    placement = dataclasses.replace(
        band_build.placement,
        frame=AreaFrame(
            width=original_frame.width,
            height=original_frame.height,
            primary_band=certified[0],
            certified_bands=certified,
            rotated=original_frame.rotated,
        ),
    )

    cli._report(dataclasses.replace(band_build, placement=placement), verbose=False)

    report = capsys.readouterr().err
    assert f"primary_band: {certified[0]}" in report
    assert f"certified_bands: {', '.join(map(str, certified))}" in report

def test_cli_reports_structured_projection_evidence_without_parsing_prose(
    band_build: pipeline.Build,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projection = ProjectionFailureRecord(
        160,
        "geom.collide",
        (4, 9),
        "first collision; left machine; right machine",
    )
    refused = LayoutAttemptFailure(
        "no-proliferator",
        "sequence-pair",
        "exact projection refused; after routing",
        (projection,),
    )

    cli._report(dataclasses.replace(band_build, refused=(refused,)), verbose=False)

    report = capsys.readouterr().err
    assert (
        "sequence-pair/no-proliferator: exact projection refused; after routing"
        in report
    )
    assert (
        "band 160 geom.collide buildings (4, 9): "
        "first collision; left machine; right machine"
    ) in report


def test_terminal_cli_refusal_prints_structured_projection_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projection = ProjectionFailureRecord(
        200,
        "game.power_too_close",
        (2, 7),
        "power envelopes; north; south",
    )
    monkeypatch.setattr(
        pipeline,
        "build",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            NoValidLayout(
                "exact projection refused",
                spec_label="no-proliferator",
                budget_s=2.0,
                projection_failures=(projection,),
            )
        ),
    )

    assert cli.main(["iron-ingot"]) == 3

    report = capsys.readouterr().err
    assert (
        "band 200 game.power_too_close buildings (2, 7): "
        "power envelopes; north; south"
    ) in report

def test_cli_refuses_success_without_band_evidence(
    band_build: pipeline.Build,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    unframed = dataclasses.replace(
        band_build,
        placement=dataclasses.replace(band_build.placement, frame=None),
    )
    monkeypatch.setattr(pipeline, "build", lambda *args, **kwargs: unframed)

    assert cli.main(["iron-ingot"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "flab2bp: successful build placement has no area frame\n"
