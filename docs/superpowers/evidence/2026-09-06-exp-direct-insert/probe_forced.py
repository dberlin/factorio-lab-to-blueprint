"""Throwaway probe: what does a direct-insert arrangement COST in width?

Runs each cell twice -- once as built, once with every direct Boolean pinned to
1 in `_pack_model` -- so the width/area difference is the price the width-first
objective refuses to pay for a bridge, and the verdict of the forced run says
whether emission could have seated it at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp.layout import finalize, freeform  # noqa: E402
from flab2bp.layout import validate as validator  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import PlacementCompletion  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_direct import CELLS, build_candidates, load_vendored, parse_url  # noqa: E402


def run(name: str, *, force: bool) -> dict[str, object]:
    url, policy, budget = CELLS[name]
    spec = build_candidates(
        load_vendored(), parse_url(url), candidate_policies=(policy,)
    ).candidates[0]
    orig = freeform._pack_model
    forced = {"models": 0, "vars": 0}

    def spy(strips, **kwargs):
        built = orig(strips, **kwargs)
        if built is not None and force and built.direct_vars:
            # ONE bridge, not all of them: forcing every candidate at once is a
            # different (and over-constrained) question from what one costs.
            pair = min(built.direct_vars)
            built.model.add(built.direct_vars[pair] == 1)
            forced["models"] += 1
            forced["vars"] += 1
        return built

    if force:
        freeform._pack_model = spy
    try:
        layout = freeform.FreeformLayout(band_policy=BandPolicy("portable"), workers=1)
        try:
            placement = layout.lay_out(spec, time_budget_s=budget)
            if placement.completion is not PlacementCompletion.COMPACTED_AND_FINALIZED:
                placement = finalize.compact_open_boundary_belts(placement, spec, expect_power=True)
                placement = finalize.finalize_placement(placement, BandPolicy("portable"))
            report = validator.validate(
                placement, spec, ids=validator.id_map(spec), expect_power=True
            )
            row: dict[str, object] = {
                "verdict": "CLEAN" if report.ok else "INVALID",
                "errors": sorted({f.check for f in report.errors})[:6],
                "skipped_checks": len(report.skipped),
                "area": float(placement.area),
                "direct_inserts": float(placement.stats.get("direct_inserts", 0)),
                "belt_tiles": float(placement.stats.get("belt_tiles", 0)),
            }
        except Exception as exc:  # noqa: BLE001 - a refusal is a datum here
            row = {"verdict": repr(exc)[:110]}
    finally:
        freeform._pack_model = orig
    row.update(cell=name, forced=force, **forced)
    return row


def main(argv: list[str]) -> int:
    out = []
    for name in argv[1:] or ["graphene"]:
        for force in (False, True):
            row = run(name, force=force)
            out.append(row)
            print(json.dumps(row), flush=True)
    Path(__file__).with_name("probe-forced.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
