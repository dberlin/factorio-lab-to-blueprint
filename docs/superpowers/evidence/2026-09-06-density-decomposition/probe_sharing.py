"""Throwaway probe: how much sharing is in a baseline freeform build?

Counts the Splitters in the finished blueprint (each one is a net branching off
a sibling's run -- the physical trace of ``_merge_frontier``) and the nets that
have a sibling on their source or destination lane.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp.dsp import catalog  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import freeform  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.rates.candidates import CandidatePolicy, build_candidates  # noqa: E402

CELLS = {
    "um60": ("https://factoriolab.github.io/dsp/list?o=universe-matrix*60&ibe=conveyor-belt-3"
             "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11",
             CandidatePolicy.NO_PROLIFERATOR),
    "qc180": ("https://factoriolab.github.io/dsp/list?o=quantum-chip*180&ibe=conveyor-belt-3"
              "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11",
              CandidatePolicy.NO_PROLIFERATOR),
    "processor60": ("https://factoriolab.github.io/dsp/list?o=processor*60&ibe=conveyor-belt-2&v=11",
                    CandidatePolicy.NO_PROLIFERATOR),
}


def main() -> int:
    #: Count how many nets the router saw with a sibling, by watching the one
    #: function that offers sibling cells.  Non-empty return = this net had a
    #: place to branch to or merge into.
    original = freeform._merge_frontier
    seen = {"calls": 0, "nonempty": 0, "cells": 0}

    def counting(*args, **kwargs):
        out = original(*args, **kwargs)
        seen["calls"] += 1
        if out:
            seen["nonempty"] += 1
            seen["cells"] += len(out)
        return out

    freeform._merge_frontier = counting
    splitter_id = catalog.get_item_id("splitter")
    data = load_vendored()
    rows = []
    for name, (url, policy) in CELLS.items():
        for k in seen:
            seen[k] = 0
        spec = build_candidates(data, parse_url(url), candidate_policies=(policy,)).candidates[0]
        layout = freeform.FreeformLayout(band_policy=BandPolicy("portable"), workers=8)
        try:
            placement = layout.lay_out(spec, time_budget_s=30.0)
        except Exception as exc:  # noqa: BLE001 - a refusal is a datum here
            rows.append({"cell": name, "verdict": repr(exc)[:80]})
            continue
        splitters = sum(1 for b in placement.buildings if b.item_id == splitter_id)
        rows.append(
            {
                "cell": name,
                "machines": int(float(placement.stats.get("machines", 0))),
                "nets": int(float(placement.stats.get("nets", 0))),
                "splitters": splitters,
                "belt_tiles": int(float(placement.stats.get("belt_tiles", 0))),
                "area": placement.area,
                "merge_frontier_calls": seen["calls"],
                "merge_frontier_nonempty": seen["nonempty"],
            }
        )
        print(json.dumps(rows[-1]), flush=True)
    Path(__file__).with_name("sharing-probe.json").write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
