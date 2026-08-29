"""The JSON has to carry what the CLI prints, not just the blueprint."""

from __future__ import annotations

import dataclasses
import json
from fractions import Fraction
from typing import Final

import pytest
from pydantic import TypeAdapter

from flab2bp import pipeline
from flab2bp.layout.base import AreaFrame
from flab2bp.layout.validate import Finding, Severity
from flab2bp.web.payload import Json, describe, refusal

_JSON_ADAPTER: Final[TypeAdapter[Json]] = TypeAdapter(Json)


def test_it_is_actually_serialisable(small_build: pipeline.Build) -> None:
    """A ``Fraction`` anywhere in here would raise, which is the point of the test."""
    assert _JSON_ADAPTER.validate_json(json.dumps(describe(small_build)))["valid"] is True


def test_the_blueprint_and_the_shape_of_the_build(small_build: pipeline.Build) -> None:
    body = describe(small_build)
    assert body["blueprint"] == small_build.blueprint
    assert str(body["blueprint"]).startswith("BLUEPRINT:")
    assert body["strategy"] == small_build.strategy
    assert body["candidate"] == small_build.spec.label
    assert body["machines"] == small_build.spec.machine_count
    assert body["area"] == small_build.placement.area


def test_payload_reports_literal_certified_bands(
    small_build: pipeline.Build,
) -> None:
    original_frame = small_build.placement.frame
    assert original_frame is not None
    framed = dataclasses.replace(
        small_build,
        placement=dataclasses.replace(
            small_build.placement,
            frame=AreaFrame(
                width=original_frame.width,
                height=original_frame.height,
                primary_band=160,
                certified_bands=(160, 200),
                rotated=original_frame.rotated,
            ),
        ),
    )

    result = describe(framed)

    assert result["primary_band"] == 160
    assert result["certified_bands"] == [160, 200]


def test_payload_refuses_success_without_band_evidence(
    small_build: pipeline.Build,
) -> None:
    unframed = dataclasses.replace(
        small_build,
        placement=dataclasses.replace(small_build.placement, frame=None),
    )

    with pytest.raises(ValueError, match="area frame"):
        describe(unframed)


def test_provenance_survives(small_build: pipeline.Build) -> None:
    """The three things that read as silence if nobody serialises them."""
    body = describe(small_build)
    # Whether the recipe selection was pinned or re-derived.
    assert body["flow_pinned"] is False
    # Whether the belt ceiling was read from the URL or assumed.
    belt = body["belt_rules"]
    assert isinstance(belt, dict)
    assert set(belt) == {"max_z", "lab_level", "vertical_construction", "from_url"}
    # What produced no layout at all, which `attempts` cannot show.
    assert isinstance(body["refused"], list)


def test_rates_keep_the_exact_fraction(small_build: pipeline.Build) -> None:
    """``5/6`` items per second does not survive a float, so both forms travel."""
    outputs = describe(small_build)["outputs"]
    assert isinstance(outputs, dict)
    for item, rate in small_build.spec.outputs.items():
        described_rate = outputs[item]
        assert isinstance(described_rate, dict)
        assert described_rate["exact"] == str(rate)
        assert Fraction(str(described_rate["exact"])) == rate
        assert described_rate["per_minute"] == float(rate * 60)


def test_an_invalid_build_withholds_the_string(small_build: pipeline.Build) -> None:
    """An invalid blueprint is worse than none, so it is not offered by default."""
    broken = dataclasses.replace(
        small_build,
        report=dataclasses.replace(
            small_build.report,
            findings=(
                *small_build.report.findings,
                Finding(check="invented", severity=Severity.ERROR, message="for the test"),
            ),
        ),
    )
    assert broken.report.ok is False

    body = describe(broken)
    assert body["blueprint"] is None
    assert body["valid"] is False
    report = body["report"]
    assert isinstance(report, dict)
    assert report["errors"] == [{"check": "invented", "message": "for the test"}]

    # ...and it IS offered when the caller says so, mirroring --allow-invalid.
    assert describe(broken, allow_invalid=True)["blueprint"] == small_build.blueprint


def test_a_refusal_keeps_one_line_per_pair() -> None:
    body = refusal(
        ["sequence-pair/a: too tall", "sequence-pair/b: unroutable"],
        message="no valid layout",
    )
    assert body["reasons"] == [
        "sequence-pair/a: too tall",
        "sequence-pair/b: unroutable",
    ]
    assert body["message"] == "no valid layout"
