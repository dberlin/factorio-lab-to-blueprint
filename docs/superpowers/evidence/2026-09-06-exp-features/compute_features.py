"""Score every spec this experiment needs, without running a single placer.

    uv run python docs/superpowers/evidence/2026-09-06-exp-features/compute_features.py

Writes ``features.jsonl`` next to this file: one row per (url, candidate
policy), covering

* the twelve corpus URLs at all three candidate policies -- the 36 specs behind
  the gate's 72 cells,
* the three large URLs (``mall``, ``zurl2``, ``belt3``) at the two policies the
  large-URL runs used, which is where the refusals actually live, and
* the 4(c) contrast pair: copper-ingot at 2000/min against a green-cube-shaped
  block sized to roughly 200 machines.

Everything is rate solve plus strip plan.  No layout, no audit, no harness.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent.parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_HERE))

from routing_features import feature_row, plan_strips_for  # noqa: E402

from flab2bp.bench.corpus import URL_CORPUS  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates  # noqa: E402

_RANK = "arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
_FAST_RANK = "plane-smelter~assembling-machine-3~quantum-chemical-plant~matrix-lab"

#: The three URLs the large-URL evidence runs used, verbatim from
#: ``docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt`` so
#: the join cannot silently score a different build than the one that refused.
LARGE_URLS: tuple[tuple[str, str], ...] = (
    (
        "belt3",
        "https://factoriolab.github.io/dsp/list?o=conveyor-belt-3*1080"
        "&ibe=conveyor-belt-3&rex=P*Y*d*k*u*BN*BU*BX*Bk~Bl*Bs*CF~CG*CQ~CR"
        "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11",
    ),
    (
        "zurl2",
        "https://factoriolab.github.io/dsp/list?z=eJwVxTEKgDAMBdDbZPhTO1hcsiSom6gg2FV0EC0FRXHK2cW3vMwt"
        "vCsdZZYC4S.AO9rmlZXO9eUOEQt23JAWMkImyG5yQC5obdpAe9OBUjo5mlhlPT3s.QdXzBnL&v=11",
    ),
    (
        "mall",
        "https://factoriolab.github.io/dsp/list?z=eJwlx7uOwjAUhOG3OcUUKAYWhWKaY4mgVRaBEBAogRQWayVyuKTys6"
        "PEzf.NNNzAZHkmDdcnzBbD0ArTXBp-YH6kod0PtyZ-hxQSqHsgk8Bd4pLQG2Ak0Fbp223yL1Em1sfkMpEPeFoY8TyPdWPL"
        "sd3YFkZc3VMn4q41rbjuybmEuucWJ5xxxwMv9FhAN9ADtILeoI-o.9Ap7CraQrwP7GIbXSzFtx0LedOYL5cQRDE_&v=11",
    ),
)

#: 4(c).  ``copper-ingot`` is the user's easy case at an absurd rate -- a huge
#: block with a trivial graph -- and the matrices are the opposite: a modest
#: machine count over a deep, wide graph.  Rates chosen to land near 200
#: machines so the contrast is topology and not size; the actual counts are in
#: the output and quoted in the README.
CONTRAST_URLS: tuple[tuple[str, str], ...] = (
    (
        "copper-ingot-2000",
        f"https://factoriolab.github.io/dsp/list?o=copper-ingot*2000&ibe=conveyor-belt-2&mmr={_RANK}&v=11",
    ),
    # The rate the user named lands at 34 machines, which is not a fair
    # comparison against a 200-machine matrix block: the whole point is to
    # separate TOPOLOGY from SIZE, so here is the same trivial graph scaled
    # until it has as many machines as the hard one.
    (
        "copper-ingot-12000",
        f"https://factoriolab.github.io/dsp/list?o=copper-ingot*12000&ibe=conveyor-belt-2&mmr={_RANK}&v=11",
    ),
    (
        "information-matrix-120",
        "https://factoriolab.github.io/dsp/list?o=information-matrix*120"
        f"&ibe=conveyor-belt-3&mmr={_RANK}&v=11",
    ),
    (
        "universe-matrix-12",
        "https://factoriolab.github.io/dsp/list?o=universe-matrix*12"
        f"&ibe=conveyor-belt-3&mmr={_FAST_RANK}&v=11",
    ),
)


def main() -> int:
    data = load_vendored()
    out = _HERE / "features.jsonl"
    rows: list[dict[str, object]] = []

    sources: list[tuple[str, str, str, str]] = [
        ("corpus", entry.url_id, entry.url, entry.tier.value) for entry in URL_CORPUS
    ]
    sources += [("large", url_id, url, "large-url") for url_id, url in LARGE_URLS]
    sources += [("contrast", url_id, url, "contrast") for url_id, url in CONTRAST_URLS]

    for source, url_id, url, tier in sources:
        t0 = time.monotonic()
        specs = build_candidates(
            data, parse_url(url), candidate_policies=DEFAULT_CANDIDATE_POLICIES
        ).candidates
        solve_s = time.monotonic() - t0
        for spec_index, spec in enumerate(specs):
            key = {
                "source": source,
                "url_id": url_id,
                "tier": tier,
                "spec_index": spec_index,
                "spec_label": spec.label,
                "rate_solve_s": round(solve_s / len(specs), 4),
            }
            t1 = time.monotonic()
            try:
                strips = plan_strips_for(spec)
                planning_error = ""
            except Exception as exc:  # noqa: BLE001 - a spec that cannot be planned is data
                strips = []
                planning_error = f"{type(exc).__name__}: {exc}"[:200]
            key["strip_plan_s"] = round(time.monotonic() - t1, 4)
            key["planning_error"] = planning_error
            row = feature_row(spec, key=key, strips=strips)
            rows.append(row)
            print(
                f"{url_id}/{spec.label}: machines={row['machines']} strips={row['strips']} "
                f"depth={row['chain_depth']} max_spread={row['max_spread']} "
                f"({key['strip_plan_s']}s)",
                flush=True,
            )

    out.write_text("".join(json.dumps(row) + "\n" for row in rows))
    print(f"WROTE {out} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
