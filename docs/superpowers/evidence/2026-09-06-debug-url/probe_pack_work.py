import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
from flab2bp.layout import freeform  # noqa: E402

freeform._DETERMINISTIC_PACK_WORK = float(sys.argv[2])  # diagnosis only
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402

spec = build_candidates(
    load_vendored(), parse_url(sys.argv[1]), candidate_policies=(CandidatePolicy(sys.argv[3]),)
).candidates[0]
s = freeform.FreeformLayout(
    belt_vertical_construction=True, band_policy=BandPolicy("portable"), workers=8
)
t0 = time.perf_counter()
KEEP = ("pack_cp", "attempts", "stale", "preparation", "detailed", "distinct")
try:
    p = s.lay_out(spec, time_budget_s=30.0)
    print(
        json.dumps(
            {
                "work": sys.argv[2],
                "policy": sys.argv[3],
                "verdict": "OK",
                "area": int(p.area),
                "wall": round(time.perf_counter() - t0, 2),
            }
        )
    )
except NoValidLayout as e:
    print(
        json.dumps(
            {
                "work": sys.argv[2],
                "policy": sys.argv[3],
                "verdict": "REFUSED",
                "reason": e.reason[:260],
                "wall": round(time.perf_counter() - t0, 2),
                "stats": {k: str(v) for k, v in sorted(e.stats.items()) if k.startswith(KEEP)},
            }
        )
    )
