"""Record the real freeform sweep for the archived steel/titanium-alloy block.

Usage: uv run python block_probe.py OUT.json URL BUDGET CAPTURE.json
Capture a real recut fixture first: block_probe.py --capture OUT.json URL BUDGET
The only instrumentation retains the existing _sweep attempt/skip containers;
it calls through once with unchanged arguments, workers and search decisions.
This is diagnosis evidence, not the uninstrumented Task 9 CLI gate.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from typing import Any
from flab2bp.lab.data import load_vendored
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.lab.url import parse_url
from flab2bp.layout import freeform, validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout, Placement
from flab2bp.layout.hierarchy.partition import Unit, sub_spec
from flab2bp.layout.hierarchy.strategy import HierarchicalLayout, _BLOCK_WORKERS
from flab2bp.layout.sequence_alns import OperatorSession
from flab2bp.rates.candidates import CandidatePolicy, build_candidates
from flab2bp.spec import BuildSpec


class RecordingFreeform(freeform.FreeformLayout):
    def __init__(self, *, vertical: bool) -> None:
        super().__init__(
            band_policy=BandPolicy.parse("portable"),
            workers=_BLOCK_WORKERS,
            belt_vertical_construction=vertical,
        )
        self.attempts: list[freeform.PackAttempt] = []
        self.skipped: list[int] = []

    def _sweep(
        self,
        spec: BuildSpec,
        strips: list[freeform.Strip],
        time_budget_s: float,
        deadline: float | None = None,
        budget: dict[str, int] | None = None,
        rejected: list[freeform._RefusalFinding] | None = None,
        attempts: list[freeform.PackAttempt] | None = None,
        skipped_heights: list[int] | None = None,
        *,
        session: OperatorSession,
        telemetry: dict[str, float | str] | None = None,
    ) -> Placement | None:
        # lay_out owns and supplies both lists. Keep references, not copies in
        # the timed path; nothing changes the candidate schedule or deadlines.
        if attempts is not None:
            self.attempts = attempts
        if skipped_heights is not None:
            self.skipped = skipped_heights
        return super()._sweep(
            spec, strips, time_budget_s, deadline, budget, rejected, attempts,
            skipped_heights, session=session, telemetry=telemetry,
        )


class RecordingHierarchy(HierarchicalLayout):
    """Retain real recut entries; never synthesize a block from a recipe subset."""

    def __init__(self, *, vertical: bool) -> None:
        super().__init__(
            band_policy=BandPolicy.parse("portable"),
            belt_vertical_construction=vertical,
        )
        self.rounds: list[tuple[float, tuple[tuple[int, tuple[Any, ...]], ...]]] = []

    def _solve_round(
        self, spec: BuildSpec, entries: list[Any], todo: list[int], **kwargs: Any
    ) -> int:
        self.rounds.append((
            kwargs["block_budget"],
            tuple((index, tuple(entry.units)) for index, entry in enumerate(entries)),
        ))
        return super()._solve_round(spec, entries, todo, **kwargs)


def capture(out: Path, url: str, budget_s: float) -> int:
    spec = build_candidates(
        load_vendored(), parse_url(url),
        candidate_policies=(CandidatePolicy.ALL_PRODUCTS,),
    ).candidates[0]
    layout = RecordingHierarchy(vertical=belt_rules_for_url(url).vertical_construction)
    record: dict[str, object] = {"url": url, "budget_s": budget_s}
    try:
        layout.lay_out(spec, time_budget_s=budget_s)
    except NoValidLayout as refusal:
        record.update(reason=refusal.reason, stats=refusal.stats)
    record["rounds"] = [
        {
            "round": ordinal,
            "block_budget_s": block_budget,
            "blocks": [
                {
                    "index": index,
                    "recipes": sorted({unit.recipe for unit in units}),
                    "units": [
                        {
                            "uid": unit.uid,
                            "group_index": spec.groups.index(unit.group),
                            "recipe": unit.recipe,
                            "count": unit.count,
                        }
                        for unit in units
                    ],
                }
                for index, units in blocks
            ],
        }
        for ordinal, (block_budget, blocks) in enumerate(layout.rounds)
    ]
    out.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
    return 0


def main(argv: list[str]) -> int:
    if argv[0] == "--capture":
        return capture(Path(argv[1]), argv[2], float(argv[3]))
    out, url, budget_s = Path(argv[0]), argv[1], float(argv[2])
    spec = build_candidates(
        load_vendored(), parse_url(url),
        candidate_policies=(CandidatePolicy.ALL_PRODUCTS,),
    ).candidates[0]
    captured = json.loads(Path(argv[3]).read_text())
    if captured["url"] != url:
        raise ValueError("capture URL does not match the replay URL")
    matches = [
        (round_record, block_record)
        for round_record in captured["rounds"]
        for block_record in round_record["blocks"]
        if block_record["recipes"] == ["steel", "titanium-alloy"]
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one captured steel/titanium-alloy block, found {len(matches)}")
    round_record, block_record = matches[0]
    index = block_record["index"]
    block = [
        Unit(unit["uid"], spec.groups[unit["group_index"]], unit["count"])
        for unit in block_record["units"]
    ]
    if [unit.recipe for unit in block] != [unit["recipe"] for unit in block_record["units"]]:
        raise ValueError("captured group identities no longer match the production spec")
    block_spec = sub_spec(spec, block, index)
    layout = RecordingFreeform(vertical=belt_rules_for_url(url).vertical_construction)
    record: dict[str, object] = {
        "block": index,
        "expected_archived_index": 20,
        "captured_round": round_record["round"],
        "captured_block_budget_s": round_record["block_budget_s"],
        "recipes": sorted({unit.recipe for unit in block}),
        "budget_s": budget_s,
        "workers": _BLOCK_WORKERS,
        "units": [asdict(unit) for unit in block],
    }
    started = time.monotonic()
    try:
        placement = layout.lay_out(block_spec, time_budget_s=budget_s)
    except NoValidLayout as refusal:
        record.update(ok=False, reason=refusal.reason, stats=refusal.stats)
    else:
        report = validate.certify(placement, block_spec, expect_power=True)
        record.update(
            ok=report.ok, area=placement.area,
            errors_by_check=dict(Counter(finding.check for finding in report.errors)),
        )
    record["wall_s"] = time.monotonic() - started
    record["skipped_heights"] = layout.skipped
    record["attempts"] = [
        {
            "height": attempt.height,
            "compact_width": attempt.compact_width,
            "origins": attempt.origins,
            "outline": attempt.outline,
            "packed_strips": len(attempt.origins),
            "nets_attempted": len(attempt.routing.routed) + len(attempt.routing.failures),
            "nets_routed": len(attempt.routing.routed),
            "routing": asdict(attempt.routing),
            "logical_failures": [
                asdict(failure.net_id.logical) for failure in attempt.routing.failures
            ],
            "failure_kinds": dict(
                Counter(failure.kind.value for failure in attempt.routing.failures)
            ),
            "budget_stage": attempt.budget_stage,
            "stranded_ports": [asdict(port) for port in attempt.stranded_ports],
        }
        for attempt in layout.attempts
    ]
    out.write_text(json.dumps(record, indent=2, sort_keys=True, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
