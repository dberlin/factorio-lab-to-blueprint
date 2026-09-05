"""Fixed cost from process start to the first candidate's placement.

Splits the pre-search span into: interpreter+import, vendored dataset load, URL
parse, rate solve (`build_candidates`, which runs the MILP), and the layout
object's construction.  Anything here is paid on EVERY build regardless of
budget, so a second spent here is a second the search never sees.

    uv run python startup_cost.py --out startup.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

PROC_START = float(os.environ.get("FLAB_T0", "0")) or time.perf_counter()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--rate", type=int, default=60)
    args = ap.parse_args()
    marks: list[tuple[str, float]] = []
    t = time.perf_counter

    t0 = t()
    from flab2bp.bench.corpus import _FAST_RANK
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.layout import route_kernel
    from flab2bp.layout.band_policy import BandPolicy
    from flab2bp.layout.freeform import FreeformLayout
    from flab2bp.layout.sequence_solver import SequencePairLayout
    from flab2bp.rates import CandidatePolicy, build_candidates
    marks.append(("import_flab2bp", t() - t0))

    t0 = t()
    data = load_vendored()
    marks.append(("load_vendored", t() - t0))

    t0 = t()
    data2 = load_vendored()
    marks.append(("load_vendored_again", t() - t0))

    url = (f"https://factoriolab.github.io/dsp/list?o=universe-matrix*{args.rate}"
           f"&ibe=conveyor-belt-3&mmr={_FAST_RANK}&v=11")
    t0 = t()
    parsed = parse_url(url)
    marks.append(("parse_url", t() - t0))

    t0 = t()
    built = build_candidates(data, parsed, candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,))
    marks.append(("build_candidates_rate_solve", t() - t0))
    spec = built.candidates[0]

    t0 = t()
    FreeformLayout(band_policy=BandPolicy("portable"), workers=8)
    marks.append(("FreeformLayout_ctor", t() - t0))
    t0 = t()
    SequencePairLayout(band_policy=BandPolicy("portable"))
    marks.append(("SequencePairLayout_ctor", t() - t0))

    row = {
        "python": sys.version.split()[0],
        "route_backend": route_kernel.selected_backend(),
        "machines": sum(g.count for g in spec.groups),
        "marks_s": {k: round(v, 4) for k, v in marks},
        "pre_search_total_s": round(sum(v for k, v in marks if k != "load_vendored_again"), 4),
        "wall_since_interpreter_start_s": round(t() - PROC_START, 4),
    }
    Path(args.out).write_text(json.dumps(row, indent=1, sort_keys=True))
    print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
