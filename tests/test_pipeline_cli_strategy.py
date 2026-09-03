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
from flab2bp.rates.candidates import CandidatePolicy


class _BuildKwargs(TypedDict, total=False):
    strategy: pipeline.StrategyName
    band: BandSelection
    candidate_policies: tuple[CandidatePolicy, ...]
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
    workers: int | None
    race: bool
    share: bool


@pytest.fixture(scope="module")
def band_build() -> pipeline.Build:
    return pipeline.build(
        "https://factoriolab.github.io/dsp/flow?o=electromagnetic-matrix*60&v=11",
        strategy="freeform",
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
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



@pytest.mark.parametrize(
    ("policy_args", "expected"),
    (
        (
            [],
            (
                CandidatePolicy.NO_PROLIFERATOR,
                CandidatePolicy.ALL_PRODUCTS,
                CandidatePolicy.OUTPUT_PRODUCTS,
            ),
        ),
        (
            ["--candidate-policy", "output-products"],
            (CandidatePolicy.OUTPUT_PRODUCTS,),
        ),
        (
            ["--candidate-policy", "output-products,no-proliferator"],
            (
                CandidatePolicy.NO_PROLIFERATOR,
                CandidatePolicy.OUTPUT_PRODUCTS,
            ),
        ),
        (
            [
                "--candidate-policy",
                "output-products",
                "--candidate-policy",
                "all-products,no-proliferator",
            ],
            (
                CandidatePolicy.NO_PROLIFERATOR,
                CandidatePolicy.ALL_PRODUCTS,
                CandidatePolicy.OUTPUT_PRODUCTS,
            ),
        ),
    ),
)
def test_cli_candidate_policy_selections_reach_pipeline_in_canonical_order(
    policy_args: list[str],
    expected: tuple[CandidatePolicy, ...],
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

    assert cli.main(["iron-ingot", *policy_args]) == 0
    assert received["candidate_policies"] == expected


@pytest.mark.parametrize(
    ("policy_args", "diagnostic"),
    (
        (["--candidate-policy", ""], "candidate policy must not be empty"),
        (
            ["--candidate-policy", "no-proliferator,"],
            "candidate policy must not be empty",
        ),
        (
            ["--candidate-policy", "no-proliferator,no-proliferator"],
            "duplicate candidate policy: no-proliferator",
        ),
        (
            [
                "--candidate-policy",
                "no-proliferator",
                "--candidate-policy",
                "no-proliferator",
            ],
            "duplicate candidate policy: no-proliferator",
        ),
        (
            ["--candidate-policy", "balanced"],
            "unknown candidate policy: 'balanced'",
        ),
    ),
)
def test_cli_rejects_invalid_candidate_policy_selections(
    policy_args: list[str],
    diagnostic: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        pipeline,
        "build",
        lambda *args, **kwargs: pytest.fail("invalid CLI arguments reached pipeline"),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["iron-ingot", *policy_args])

    assert exc_info.value.code == 2
    assert diagnostic in capsys.readouterr().err

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
        placement=dataclasses.replace(
            band_build.placement,
            frame=None,
            completion=None,
        ),
    )
    monkeypatch.setattr(pipeline, "build", lambda *args, **kwargs: unframed)

    assert cli.main(["iron-ingot"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "flab2bp: successful build placement has no area frame\n"


def test_the_cli_offers_racing_as_an_opt_in() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["https://example/x"])
    assert args.race is False
    assert args.share is True
    assert args.workers is None

    opted_in = parser.parse_args(
        ["https://example/x", "--race", "--no-share", "--workers", "8"]
    )
    assert opted_in.race is True
    assert opted_in.share is False
    assert opted_in.workers == 8


def test_the_cli_forwards_every_race_knob_to_the_pipeline(
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
        cli.main(["iron-ingot", "--race", "--no-share", "--workers", "9"]) == 0
    )

    assert received["workers"] == 9
    assert received["race"] is True
    assert received["share"] is False


def test_the_cli_leaves_the_race_knobs_at_their_pipeline_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `--race` is an OPT-IN until the flip task, so a plain invocation must
    # forward the same three values `pipeline.build` would have defaulted to.
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

    assert cli.main(["iron-ingot"]) == 0

    assert received["workers"] is None
    assert received["race"] is False
    assert received["share"] is True


def test_sequence_islands_are_legal_with_best_and_reach_the_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The islands live inside the raced sequence-pair arm, so `best` is now a
    # legal companion for the flag -- and an explicit N must actually TRAVEL,
    # not be silently flattened to 1 by the sequence-pair-only derivation.
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
        cli.main(["iron-ingot", "--strategy", "best", "--sequence-islands", "4"]) == 0
    )

    assert received["sequence_islands"] == 4


def test_best_without_the_flag_still_runs_one_island(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `best` is the DEFAULT strategy, so the affinity-capped auto default must
    # stay exclusive to explicit sequence-pair: defaulting it here would change
    # every plain `flab2bp <url>` build.
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
    monkeypatch.setattr(cli, "_available_cpu_count", lambda: 64)

    assert cli.main(["iron-ingot", "--strategy", "best"]) == 0

    assert received["sequence_islands"] == 1


@pytest.mark.parametrize("workers", (0, -1))
def test_cli_rejects_a_non_positive_workers_count(
    workers: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        pipeline,
        "build",
        lambda *args, **kwargs: pytest.fail("invalid CLI arguments reached pipeline"),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["iron-ingot", "--workers", str(workers)])

    assert exc_info.value.code == 2
    assert "--workers must be a positive integer" in capsys.readouterr().err
