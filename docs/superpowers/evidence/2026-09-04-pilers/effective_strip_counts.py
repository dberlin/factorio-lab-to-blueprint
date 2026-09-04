#!/usr/bin/env python3
"""Emit effective pre-search strip and piler counts for the 72 audit cells.

Run from a frozen source archive root.  The helper deliberately intercepts the
production seams reached only after each strategy's deterministic preprocessing;
it never calls ``plan_strips`` itself and has no raw-plan fallback.
"""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn


class _SeamCaptured(BaseException):
    """Stop a layout exactly when its effective strips reach the search seam."""


def _require_seams(freeform: Any, sequence_solver: Any) -> tuple[Any, Any]:
    try:
        freeform_seam = freeform._machines_without_poses
        sequence_seam = sequence_solver._variant_search_inputs
    except AttributeError as exc:
        raise SystemExit(f"required effective-strip seam unavailable: {exc}") from exc

    freeform_signature = inspect.signature(freeform_seam)
    expected_freeform = ("strips",)
    if tuple(freeform_signature.parameters) != expected_freeform:
        raise SystemExit(
            "required Freeform seam signature unavailable: "
            f"_machines_without_poses{freeform_signature}, expected (strips)"
        )

    sequence_signature = inspect.signature(sequence_seam)
    expected_sequence = ("spec", "strips", "families", "strip_len")
    if tuple(sequence_signature.parameters) != expected_sequence:
        raise SystemExit(
            "required SequencePair seam signature unavailable: "
            f"_variant_search_inputs{sequence_signature}, expected "
            "(spec, strips, *, families=None, strip_len)"
        )
    parameters = sequence_signature.parameters
    if (
        parameters["families"].kind is not inspect.Parameter.KEYWORD_ONLY
        or parameters["families"].default is not None
        or parameters["strip_len"].kind is not inspect.Parameter.KEYWORD_ONLY
        or parameters["strip_len"].default is not inspect.Parameter.empty
    ):
        raise SystemExit(
            "required SequencePair seam keyword contract unavailable: "
            f"_variant_search_inputs{sequence_signature}"
        )
    return freeform_seam, sequence_seam


def _piler_count(strips: Sequence[Any]) -> int:
    total = 0
    for strip in strips:
        for plan in getattr(strip, "pilers", ()):
            count = getattr(plan, "count", None)
            if type(count) is not int or count < 1:
                raise SystemExit(f"effective strip carries an invalid piler plan: {plan!r}")
            total += count
    return total


def _capture_freeform(
    freeform: Any,
    strategy: Any,
    spec: Any,
) -> tuple[int, int]:
    captured: tuple[int, int] | None = None
    original = freeform._machines_without_poses

    def intercept(strips: list[Any]) -> NoReturn:
        nonlocal captured
        if captured is not None:
            raise SystemExit("Freeform effective-strip seam was reached more than once")
        captured = (len(strips), _piler_count(strips))
        raise _SeamCaptured

    freeform._machines_without_poses = intercept
    try:
        try:
            strategy.lay_out(spec, time_budget_s=30.0)
        except _SeamCaptured:
            pass
    finally:
        freeform._machines_without_poses = original
    if captured is None:
        raise SystemExit("Freeform effective-strip seam was not reached")
    return captured


def _capture_sequence_pair(
    sequence_solver: Any,
    strategy: Any,
    spec: Any,
) -> tuple[int, int]:
    captured: tuple[int, int] | None = None
    original = sequence_solver._variant_search_inputs

    def intercept(
        seam_spec: Any,
        strips: list[Any],
        *,
        families: Sequence[Any] | None = None,
        strip_len: int,
    ) -> NoReturn:
        del families, strip_len
        nonlocal captured
        if seam_spec is not spec:
            raise SystemExit("SequencePair seam received a different BuildSpec instance")
        if captured is not None:
            raise SystemExit("SequencePair effective-strip seam was reached more than once")
        captured = (len(strips), _piler_count(strips))
        raise _SeamCaptured

    sequence_solver._variant_search_inputs = intercept
    try:
        try:
            strategy.lay_out(spec, time_budget_s=30.0)
        except _SeamCaptured:
            pass
    finally:
        sequence_solver._variant_search_inputs = original
    if captured is None:
        raise SystemExit("SequencePair effective-strip seam was not reached")
    return captured


def main() -> int:
    archive = Path.cwd().resolve()
    audit_path = archive / "scripts" / "audit.py"
    if not audit_path.is_file():
        raise SystemExit("run this helper from a frozen archive root containing scripts/audit.py")

    sys.path.insert(0, str(archive))
    sys.path.insert(0, str(archive / "src"))
    sys.path.insert(0, str(archive / "scripts"))

    import audit  # type: ignore[import-not-found]  # noqa: PLC0415
    from flab2bp.layout import freeform, sequence_solver  # noqa: PLC0415

    _require_seams(freeform, sequence_solver)
    jobs = audit.build_jobs(
        list(audit.strategy_names("both")),
        set(audit._TIER_ORDER),
        [30.0],
        8,
    )
    if len(jobs) != 72:
        raise SystemExit(f"default audit matrix has {len(jobs)} cells, expected 72")

    records: list[dict[str, object]] = []
    for job in jobs:
        specs = audit._specs_for(job.url, job.candidate_policies)
        if job.spec_index >= len(specs):
            raise SystemExit(f"missing candidate spec for {job.url_id}/#{job.spec_index}")
        spec = specs[job.spec_index]
        belt_rules = audit._belt_rules_for(job.url)
        strategy = audit._STRATEGIES[job.strategy](
            job.workers,
            belt_rules.vertical_construction,
            belt_rules.max_z,
        )
        if job.strategy == "freeform":
            strip_count, pilers = _capture_freeform(freeform, strategy, spec)
        elif job.strategy == "sequence-pair":
            strip_count, pilers = _capture_sequence_pair(sequence_solver, strategy, spec)
        else:
            raise SystemExit(f"unexpected explicit strategy: {job.strategy}")
        records.append(
            {
                "effective_strips": strip_count,
                "pilers": pilers,
                "spec_index": job.spec_index,
                "spec_label": spec.label,
                "strategy": job.strategy,
                "url_id": job.url_id,
            }
        )

    records.sort(key=lambda row: (row["strategy"], row["url_id"], row["spec_index"]))
    if len(records) != 72:
        raise SystemExit(f"captured {len(records)} cells, expected 72")
    for record in records:
        print(json.dumps(record, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
