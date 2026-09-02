"""Prove the shared geometry memo changes no prepared problem on any corpus spec.

    uv run python scripts/prepare_parity.py

For every corpus URL and candidate policy, prepare the greedy pack once with a
private cache and twice with the spec-scoped memo, and require structural
equality.  Exits non-zero on the first mismatch.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.bench.corpus import URL_CORPUS  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import geometry_memo  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.freeform import (  # noqa: E402
    _greedy_pack,
    _height_seed,
    _prepare_routing_problem,
    plan_strips,
)
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates  # noqa: E402


def main() -> int:
    data = load_vendored()
    policy = BandPolicy("portable")
    checked = 0
    for entry in URL_CORPUS:
        specs = build_candidates(
            data, parse_url(entry.url), candidate_policies=DEFAULT_CANDIDATE_POLICIES
        ).candidates
        for spec in specs:
            strips = plan_strips(spec, strip_len=6, band_policy=policy)
            pack = _greedy_pack(strips, _height_seed(strips))
            cold = _prepare_routing_problem(spec, strips, pack, policy=policy, power=True)
            shared = geometry_memo.for_spec(spec)
            for repeat in (1, 2):
                warm = _prepare_routing_problem(
                    spec, strips, pack, policy=policy, power=True, staged_static_cache=shared
                )
                if warm != cold:
                    print(f"MISMATCH {entry.url_id}/{spec.label} on repeat {repeat}")
                    return 1
            checked += 1
            print(f"ok {entry.url_id}/{spec.label}")
    print(f"PARITY {checked} specs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
