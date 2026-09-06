"""URL -> whole ``BuildSpec``, replicating the front half of ``pipeline.build``.

Throwaway spike code. It deliberately re-implements only the part of
``pipeline.build`` that runs BEFORE the layout stage, so the prototype gets the
exact same ``BuildSpec`` the production pipeline would hand a placer, and then
decomposes it instead of laying it out whole.
"""

from __future__ import annotations

from dataclasses import dataclass

from flab2bp.dsp import catalog
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.lab.url import parse_url
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, _build_candidates_canonical
from flab2bp.spec import BuildSpec

URLS = {
    "belt3": (
        "https://factoriolab.github.io/dsp/list?o=conveyor-belt-3*1080"
        "&ibe=conveyor-belt-3&rex=P*Y*d*k*u*BN*BU*BX*Bk~Bl*Bs*CF~CG*CQ~CR"
        "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
    ),
    "zurl2": (
        "https://factoriolab.github.io/dsp/list?z=eJwVxTEKgDAMBdDbZPhTO1hcsiSom6gg2FV0EC0FRXHK2cW3vMwtvCsdZZYC4S"
        ".AO9rmlZXO9eUOEQt23JAWMkImyG5yQC5obdpAe9OBUjo5mlhlPT3s.QdXzBnL&v=11"
    ),
    "mall": (
        "https://factoriolab.github.io/dsp/list?z=eJwlx7uOwjAUhOG3OcUUKAYWhWKaY4mgVRaBEBAogRQWayVyuKTys6PEzf"
        ".NNNzAZHkmDdcnzBbD0ArTXBp-YH6kod0PtyZ-hxQSqHsgk8Bd4pLQG2Ak0Fbp223yL1Em1sfkMpEPeFoY8TyPdWPLsd3YFkZc"
        "3VMn4q41rbjuybmEuucWJ5xxxwMv9FhAN9ADtILeoI-o.9Ap7CraQrwP7GIbXSzFtx0LedOYL5cQRDE_&v=11"
    ),
}


@dataclass(frozen=True)
class Loaded:
    label: str
    policy: str
    spec: BuildSpec
    belt_rules: catalog.BeltAltitudeRules


def load(label: str, policy: str = "all-products") -> Loaded:
    """Return the whole-spec ``BuildSpec`` for ``label`` under ``policy``."""
    url = URLS[label]
    data = canonicalize_dataset(load_vendored())
    request = canonicalize_request(parse_url(url))
    belt_rules = belt_rules_for_url(url, data)
    spec_set = _build_candidates_canonical(
        data,
        request,
        tier=None,
        candidate_policies=DEFAULT_CANDIDATE_POLICIES,
        flow=None,
    )
    for candidate in spec_set.candidates:
        if candidate.label == policy:
            return Loaded(label, policy, candidate, belt_rules)
    raise SystemExit(
        f"{label}: no candidate labelled {policy!r}; have "
        + ", ".join(repr(c.label) for c in spec_set.candidates)
    )
