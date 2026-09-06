"""Throwaway probe: Splitters and belt tiles with the trunk off vs on.

The harness reports neither, so this builds ``universe-matrix@60`` once per arm
and counts the Splitters in the finished blueprint.  Each Splitter is a
physical branch point -- either ``_merge_frontier`` letting a net leave a
sibling's run, or a trunk tap.  Run ONE arm per invocation (``off``/``on``) so
that no more than two layouts are ever in flight on this shared box.
"""

from __future__ import annotations

import json
import os
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

URL = (
    "https://factoriolab.github.io/dsp/list?o=universe-matrix*60&ibe=conveyor-belt-3"
    "&mmr=plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab&v=11"
)


def main() -> int:
    arm = sys.argv[1]
    os.environ["FLAB2BP_TRUNK_ITEMS"] = "auto" if arm == "on" else ""
    splitter_id = catalog.get_item_id("splitter")
    spec = build_candidates(
        load_vendored(),
        parse_url(URL),
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    ).candidates[0]
    layout = freeform.FreeformLayout(band_policy=BandPolicy("portable"), workers=8)
    row: dict[str, object] = {"arm": arm}
    try:
        placement = layout.lay_out(spec, time_budget_s=60.0)
    except Exception as exc:  # noqa: BLE001 - a refusal is a result here
        row["verdict"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    else:
        row["verdict"] = "OK"
        row["area"] = float(placement.area)
        row["splitters"] = sum(
            1 for b in placement.buildings if b.item_id == splitter_id
        )
        row["belts"] = sum(1 for b in placement.buildings if catalog.is_belt(b.item_id))
        row["stats"] = {k: str(v) for k, v in dict(placement.stats).items()}
    print(json.dumps(row, sort_keys=True))
    Path(__file__).with_name(f"splitters-{arm}.json").write_text(
        json.dumps(row, indent=1, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
