import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
from flab2bp.layout import freeform  # noqa: E402

freeform.C_SWEEP_STALE_DRAWS = 10**6  # diagnosis only: never stale-stop
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402
from flab2bp.rates import CandidatePolicy, build_candidates  # noqa: E402

U = sys.argv[1]
spec = build_candidates(
    load_vendored(), parse_url(U), candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,)
).candidates[0]
s = freeform.FreeformLayout(
    belt_vertical_construction=True, band_policy=BandPolicy("portable"), workers=8
)
t0 = time.perf_counter()
try:
    p = s.lay_out(spec, time_budget_s=30.0)
    print(
        json.dumps(
            {"verdict": "OK", "area": int(p.area), "wall": round(time.perf_counter() - t0, 2)}
        )
    )
except NoValidLayout as e:
    print(
        json.dumps(
            {
                "verdict": "REFUSED",
                "reason": e.reason,
                "wall": round(time.perf_counter() - t0, 2),
                "stats": {
                    k: str(v)
                    for k, v in sorted(e.stats.items())
                    if k.startswith(("pack_cp", "attempts", "stale", "preparation", "detailed"))
                },
            },
            indent=1,
        )
    )
