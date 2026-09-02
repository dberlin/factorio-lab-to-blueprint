"""The JSON has to carry what the CLI prints, not just the blueprint."""

from __future__ import annotations

import dataclasses
import json
from fractions import Fraction
from typing import Final

import pytest
from pydantic import TypeAdapter

from flab2bp import pipeline
from flab2bp.layout.base import (
    AreaFrame,
    LayoutAttemptFailure,
    ProjectionFailureRecord,
)
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


def test_each_built_attempt_carries_its_real_blueprint(
    small_build: pipeline.Build,
) -> None:
    body = describe(small_build)
    attempts = body["attempts"]
    assert isinstance(attempts, list)
    attempt = attempts[0]
    assert isinstance(attempt, dict)
    assert "blueprint" in attempt
    assert attempt["blueprint"] == small_build.blueprint

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
        placement=dataclasses.replace(
            small_build.placement,
            frame=None,
            completion=None,
        ),
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


def test_each_attempt_carries_its_own_detail(small_build: pipeline.Build) -> None:
    """The candidate table selects what the report describes, so every attempt
    carries its own boundary facts rather than inheriting the winner's."""
    sprayed = small_build.spec.model_copy(
        update={
            "external_inputs": {
                **small_build.spec.external_inputs,
                "proliferator-mk-iii": Fraction(1),
            }
        }
    )
    retitled = dataclasses.replace(
        small_build.attempts[0].placement,
        short_desc="electromagnetic-matrix 60/min (all products)",
        stats={**small_build.attempts[0].placement.stats, "input_markers": 0},
    )
    other = dataclasses.replace(
        small_build.attempts[0],
        candidate="all-products",
        spec=sprayed,
        placement=retitled,
    )
    multi = dataclasses.replace(small_build, attempts=(*small_build.attempts, other))

    body = describe(multi)
    listed = body["attempts"]
    assert isinstance(listed, list)
    winner, loser = listed
    assert isinstance(winner, dict) and isinstance(loser, dict)
    winner_detail = winner["detail"]
    loser_detail = loser["detail"]
    assert isinstance(winner_detail, dict) and isinstance(loser_detail, dict)

    # The winner's detail is exactly what the top level has always said.
    for field in (
        "machines",
        "buildings",
        "primary_band",
        "certified_bands",
        "title",
        "outputs",
        "external_inputs",
        "input_markers",
        "unmarked_inputs",
        "report",
    ):
        assert winner_detail[field] == body[field]

    # The loser's differs where the candidate differs: belt-in, markers, title.
    loser_inputs = loser_detail["external_inputs"]
    assert isinstance(loser_inputs, dict)
    assert "proliferator-mk-iii" in loser_inputs
    assert loser_inputs != body["external_inputs"]
    loser_unmarked = loser_detail["unmarked_inputs"]
    assert isinstance(loser_unmarked, list)
    assert "proliferator-mk-iii" in loser_unmarked
    assert loser_detail["title"] == "electromagnetic-matrix 60/min (all products)"
    assert loser_detail["input_markers"] == 0


def test_an_attempt_without_a_frame_is_a_payload_error(
    small_build: pipeline.Build,
) -> None:
    """An attempt with no band evidence is refused, like the chosen one is."""
    unframed = dataclasses.replace(
        small_build.attempts[0],
        placement=dataclasses.replace(
            small_build.attempts[0].placement,
            frame=None,
            completion=None,
        ),
    )
    built = dataclasses.replace(small_build, attempts=(unframed,))

    with pytest.raises(ValueError, match="area frame"):
        describe(built)


def test_a_refusal_keeps_structured_projection_records_inside_attempt_boundaries() -> None:
    first = ProjectionFailureRecord(
        band=160,
        check="geom.collide",
        buildings=(4, 9),
        detail="first collision; left machine; right machine",
    )
    second = ProjectionFailureRecord(
        band=200,
        check="game.power_too_close",
        buildings=(2, 7),
        detail="power envelopes; north; south",
    )
    attempts = (
        LayoutAttemptFailure(
            "a",
            "sequence-pair",
            "no scheduled stage; exact projection refused",
            (first, second),
        ),
        LayoutAttemptFailure("b", "freeform", "unroutable"),
    )

    body = refusal(attempts, message="no valid layout")

    assert body == {
        "message": "no valid layout",
        "attempts": [
            {
                "candidate": "a",
                "strategy": "sequence-pair",
                "reason": "no scheduled stage; exact projection refused",
                "projection_failures": [
                    {
                        "band": 160,
                        "check": "geom.collide",
                        "buildings": [4, 9],
                        "detail": "first collision; left machine; right machine",
                    },
                    {
                        "band": 200,
                        "check": "game.power_too_close",
                        "buildings": [2, 7],
                        "detail": "power envelopes; north; south",
                    },
                ],
            },
            {
                "candidate": "b",
                "strategy": "freeform",
                "reason": "unroutable",
                "projection_failures": [],
            },
        ],
    }
