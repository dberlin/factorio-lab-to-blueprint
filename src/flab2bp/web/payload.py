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

from fractions import Fraction
from typing import Any

from flab2bp import pipeline
from flab2bp.layout import markers

#: A JSON object.  ``Any`` rather than ``object`` because ``json.dumps`` is
#: typed loosely and every consumer here is the encoder itself.
Json = dict[str, Any]


def _rate(value: Fraction) -> Json:
    """A rate as both the exact figure and the one a player reads.

    The exact ``Fraction`` is kept as a string because it is the only lossless
    form -- ``5/6`` items per second does not survive a float -- and the
    per-minute float is alongside it purely so the UI has something to print.
    Nothing downstream computes with either; the arithmetic already happened.
    """
    return {"exact": str(value), "per_minute": float(value * 60)}


def _rates(values: dict[str, Fraction]) -> Json:
    return {item: _rate(rate) for item, rate in sorted(values.items())}


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

    return {
        "blueprint": build.blueprint if (valid or allow_invalid) else None,
        "valid": valid,
        "strategy": build.strategy,
        "candidate": build.spec.label,
        "machines": build.spec.machine_count,
        "area": build.placement.area,
        "buildings": len(build.placement.buildings),
        "title": build.placement.short_desc,
        "description": build.placement.description,
        "outputs": _rates(dict(build.spec.outputs)),
        "external_inputs": _rates(dict(build.spec.external_inputs)),
        "input_markers": int(build.placement.stats.get("input_markers", 0)),
        "unmarked_inputs": sorted(unmarked),
        "flow_pinned": build.flow_pinned,
        "flow_findings": list(build.flow_findings),
        "belt_rules": belt,
        # Refusals travel with a successful build too: "spine refused this
        # candidate" is invisible in `attempts`, and silence there reads as
        # "it simply was not the best", which is a much more reassuring claim
        # than the truth.
        "refused": list(build.refused),
        "report": {
            "ok": build.report.ok,
            "checks_run": list(build.report.checks_run),
            "skipped": list(build.report.skipped),
            "errors": [
                {"check": f.check, "message": f.message} for f in build.report.errors
            ],
            "warnings": [
                {"check": f.check, "message": f.message} for f in build.report.warnings
            ],
        },
        "attempts": [
            {
                "candidate": a.candidate,
                "strategy": a.strategy,
                "area": a.area,
                "ok": a.ok,
                "errors": len(a.report.errors),
                "chosen": a.candidate == build.spec.label and a.strategy == build.strategy,
            }
            for a in sorted(build.attempts, key=lambda a: (not a.ok, a.area))
        ],
    }


def refusal(reasons: list[str], *, message: str) -> Json:
    """A ``NoValidLayout`` as a result rather than an error.

    ``reasons`` is the per-pair list the pipeline collected; ``message`` is the
    exception's own text, which already explains that a spec nobody can lay out
    is a defect in the layout model rather than a hard instance.  Both are kept:
    the list says what was tried, the message says how to read it.
    """
    return {"message": message, "reasons": reasons}
