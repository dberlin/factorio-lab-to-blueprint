"""A :class:`~flab2bp.pipeline.Build` as JSON.

This is the web twin of ``cli._report``, and it exists for the same reason that
function does: the blueprint string is the smallest interesting thing a build
produces.  What was refused and why, whether the recipe selection was pinned or
re-derived, and whether the belt ceiling was read or assumed are the parts a
player has to know before trusting the result, and all three read as silence if
nobody serialises them.

Two rules the CLI already follows and this must not break:

* **A refusal is a result.**  ``NoValidLayout`` says which strategy/candidate
  pairs produced nothing and why, and that reason is the useful output -- so it
  is serialised into a shape the UI can render as an answer, not as a crash.
* **An invalid blueprint is worse than no blueprint.**  ``pipeline.build`` will
  return its least-bad attempt when nothing validated, so the string is withheld
  unless the caller explicitly asked for it, exactly as ``--allow-invalid`` does.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from fractions import Fraction
from typing import cast

from flab2bp import pipeline
from flab2bp.layout import markers, validate
from flab2bp.layout.base import LayoutAttemptFailure, Placement, ProjectionFailureRecord
from flab2bp.spec import BuildSpec

#: Recursive JSON values, with no escape hatch for non-serialisable objects.
type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | Json
type Json = dict[str, JsonValue]


def _array(values: Iterable[JsonValue]) -> list[JsonValue]:
    """Materialise a JSON array without invariant container escape hatches."""
    return list(values)


def _rate(value: Fraction) -> Json:
    """A rate as both the exact figure and the one a player reads.

    The exact ``Fraction`` is kept as a string because it is the only lossless
    form -- ``5/6`` items per second does not survive a float -- and the
    per-minute float is alongside it purely so the UI has something to print.
    Nothing downstream computes with either; the arithmetic already happened.
    """
    return {"exact": str(value), "per_minute": float(value * 60)}


def _rates(values: dict[str, Fraction]) -> Json:
    result: Json = {}
    for item, rate in sorted(values.items()):
        result[item] = _rate(rate)
    return result


def _report_block(report: validate.Report) -> Json:
    """A validation report as JSON, identical shape for the winner and losers."""
    return {
        "ok": report.ok,
        "checks_run": _array(report.checks_run),
        "skipped": _array(report.skipped),
        "errors": [
            {"check": finding.check, "message": finding.message}
            for finding in report.errors
        ],
        "warnings": [
            {"check": finding.check, "message": finding.message}
            for finding in report.warnings
        ],
    }


def _belt_tiers(spec: BuildSpec, placement: Placement, report: validate.Report) -> Json:
    """The floor FactorioLab chose, the ceiling the save allows, and what was raised."""
    tiers = spec.belt_tiers
    upgraded = placement.stats.get("belt_upgrade_tiers", [])
    lanes: list[Json] = [
        {
            "item": cast(str, finding.detail["item"]),
            "lanes": cast(int, finding.detail["entry_lanes"]),
            "lanes_needed": cast(int, finding.detail["lanes_needed"]),
        }
        for finding in report.by_check("flow.external_entry_points")
    ]
    sorted_lanes: list[Json] = sorted(lanes, key=lambda lane: str(lane["item"]))
    return {
        "floor": tiers[0].item_id,
        "ceiling": tiers[-1].item_id,
        # The URL's `ist`.  Always present, even at 1, so a reader never has to
        # tell "this save does not stack" from "this payload predates stacking".
        "stack": spec.belt_stack,
        "runs_upgraded": int(placement.stats.get("belt_runs_upgraded", 0)),
        "upgrade_tiers": _array(sorted(upgraded)),
        "entry_lanes": _array(sorted_lanes),
    }


def _attempt_detail(attempt: pipeline.Attempt) -> Json:
    """One attempt's own facts: what IT belts in, makes, and costs.

    The candidate table lets a player view a losing attempt, and the report
    above it must follow that selection rather than keep describing the
    winner -- an ``all-products`` selection next to a ``no-proliferator``
    winner differs in machines, in belt-in, and in markers.
    """
    frame = attempt.placement.frame
    if frame is None:
        raise ValueError("successful build placement has no area frame")
    spec = attempt.spec
    unmarked = markers.unmarked_external_inputs(attempt.placement, spec)
    return {
        "machines": spec.machine_count,
        "buildings": len(attempt.placement.buildings),
        "primary_band": frame.primary_band,
        "certified_bands": _array(frame.certified_bands),
        "title": attempt.placement.short_desc,
        "outputs": _rates(dict(spec.outputs)),
        "external_inputs": _rates(dict(spec.external_inputs)),
        "input_markers": int(attempt.placement.stats.get("input_markers", 0)),
        "unmarked_inputs": _array(sorted(unmarked)),
        "belt_tiers": _belt_tiers(spec, attempt.placement, attempt.report),
        "report": _report_block(attempt.report),
    }

def projection_failure(failure: ProjectionFailureRecord) -> Json:
    """One exact projection refusal without flattening its evidence."""
    return {
        "band": failure.band,
        "check": failure.check,
        "buildings": _array(failure.buildings),
        "detail": failure.detail,
    }


def attempt_failure(attempt: LayoutAttemptFailure) -> Json:
    """One strategy/candidate refusal and its ordered projection evidence."""
    return {
        "candidate": attempt.candidate,
        "strategy": attempt.strategy,
        "reason": attempt.reason,
        "projection_failures": _array(
            projection_failure(failure)
            for failure in attempt.projection_failures
        ),
    }



def describe(build: pipeline.Build, *, allow_invalid: bool = False) -> Json:
    """Everything the CLI prints, plus the blueprint, as one JSON object.

    ``blueprint`` is ``None`` when validation failed and ``allow_invalid`` is
    false.  That is not a lossy summary -- ``valid`` and ``report.errors`` say
    exactly what happened -- it is the same refusal the CLI makes, moved to the
    place the string would otherwise be copied from.
    """
    unmarked = markers.unmarked_external_inputs(build.placement, build.spec)
    rules = build.belt_rules
    valid = build.report.ok
    frame = build.placement.frame
    if frame is None:
        raise ValueError("successful build placement has no area frame")

    belt: Json | None = None
    if rules is not None:
        belt = {
            "max_z": float(rules.max_z),
            "lab_level": rules.lab_level,
            "vertical_construction": rules.vertical_construction,
            # "we assumed a fully-researched save" and "the URL told us" are
            # very different claims about a ceiling, and only one of them is
            # safe to build against.
            "from_url": rules.from_url,
        }

    attempts: list[JsonValue] = [
        {
            "candidate": attempt.candidate,
            "strategy": attempt.strategy,
            "area": attempt.area,
            "ok": attempt.ok,
            "errors": len(attempt.report.errors),
            "chosen": (
                attempt.candidate == build.spec.label
                and attempt.strategy == build.strategy
            ),
            "blueprint": attempt.blueprint if (attempt.ok or allow_invalid) else None,
            "detail": _attempt_detail(attempt),
        }
        for attempt in sorted(build.attempts, key=lambda item: (not item.ok, item.area))
    ]

    return {
        "blueprint": build.blueprint if (valid or allow_invalid) else None,
        "valid": valid,
        "strategy": build.strategy,
        "candidate": build.spec.label,
        "machines": build.spec.machine_count,
        "area": build.placement.area,
        "primary_band": frame.primary_band,
        "certified_bands": _array(frame.certified_bands),
        "buildings": len(build.placement.buildings),
        "title": build.placement.short_desc,
        "description": build.placement.description,
        "outputs": _rates(dict(build.spec.outputs)),
        "external_inputs": _rates(dict(build.spec.external_inputs)),
        "input_markers": int(build.placement.stats.get("input_markers", 0)),
        "unmarked_inputs": _array(sorted(unmarked)),
        "flow_pinned": build.flow_pinned,
        "flow_findings": _array(build.flow_findings),
        "belt_rules": belt,
        "belt_tiers": _belt_tiers(build.spec, build.placement, build.report),
        # Refusals travel with a successful build too: "sequence-pair refused
        # this candidate" is invisible in `attempts`, and silence there reads
        # as "it simply was not the best", which is a much more reassuring
        # claim than the truth.
        "refused": _array(attempt_failure(attempt) for attempt in build.refused),
        "report": _report_block(build.report),
        "attempts": attempts,
    }


def refusal(attempts: Sequence[LayoutAttemptFailure], *, message: str) -> Json:
    """A ``NoValidLayout`` as a structured result rather than an error.

    Attempt boundaries and projection fields remain data all the way to the
    browser.  In particular, semicolons in a validator's human-readable detail
    cannot be mistaken for separators between attempts or failures.
    """
    return {
        "message": message,
        "attempts": _array(attempt_failure(attempt) for attempt in attempts),
    }
