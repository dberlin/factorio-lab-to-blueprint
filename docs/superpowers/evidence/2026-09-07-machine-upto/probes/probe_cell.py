"""Build one production cell, preserving full certification and stable blueprint bytes.

Adapted from 2026-09-07-exp-coater-node/probes/probe_cell.py. Unlike its
placement-field digest, this probe hashes the complete encoded blueprint with
only the creation timestamp fixed to zero. The baseline runs this same script
without --machine-rank, so it needs no new API or imports in its checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import flab2bp
from flab2bp import pipeline
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.dsp import codec
from flab2bp.dsp.records import is_belt
from flab2bp.layout.base import NoValidLayout
from flab2bp.rates.candidates import CandidatePolicy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url_id")
    parser.add_argument("policy", choices=[policy.value for policy in CandidatePolicy])
    parser.add_argument("--url", default="")
    parser.add_argument("--strategy", choices=("freeform", "sequence-pair"), default="freeform")
    parser.add_argument("--budget", type=float, default=30)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--machine-rank", choices=("exact", "up-to"))
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--bp", type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    imported = Path(flab2bp.__file__).resolve()
    if not imported.is_relative_to(root):
        raise RuntimeError(f"wrong checkout imported: {imported}; expected {root}")
    row = {
        "url_id": args.url_id,
        "policy": args.policy,
        "strategy": args.strategy,
        "machine_rank": args.machine_rank or "base",
        "workers": args.workers,
        "budget": args.budget,
        "checkout": str(root),
        "imported": str(imported),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    }
    kwargs = {}
    if args.machine_rank is not None:
        from flab2bp.rates.machine_choice import MachineRank

        kwargs["machine_rank"] = MachineRank(args.machine_rank)
    if args.strategy == "sequence-pair":
        kwargs["sequence_islands"] = 1
    start = time.monotonic()
    try:
        url = args.url or next(entry.url for entry in URL_CORPUS if entry.url_id == args.url_id)
        build = pipeline.build(
            url,
            strategy=args.strategy,
            candidate_policies=(CandidatePolicy(args.policy),),
            time_budget_s=args.budget,
            workers=args.workers,
            **kwargs,
        )
        blueprint = codec.encode(build.placement, timestamp=0)
        row.update(
            status="CLEAN" if build.report.ok else "INVALID",
            machines=build.spec.machine_count,
            area=build.placement.area,
            belt_tiles=sum(is_belt(building.item_id) for building in build.placement.buildings),
            digest=hashlib.sha256(blueprint.encode()).hexdigest(),
            errors=[{"check": finding.check, "message": finding.message} for finding in build.report.errors],
            findings=[
                {"severity": finding.severity.name, "check": finding.check, "message": finding.message}
                for finding in build.report.findings
            ],
            machine_moves=[move.model_dump() for move in getattr(build.spec, "machine_moves", ())],
        )
        if args.bp:
            args.bp.write_text(blueprint + "\n")
    except NoValidLayout as exc:
        row.update(status="REFUSED", detail=str(exc), digest=None)
    except Exception as exc:
        row.update(status="CRASH", detail=f"{type(exc).__name__}: {exc}", digest=None)
    row["seconds"] = time.monotonic() - start
    args.json.write_text(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps(row, sort_keys=True))
    return 0 if row["status"] == "CLEAN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
