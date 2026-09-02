from __future__ import annotations

import inspect

from flab2bp.rates import CandidatePolicy
from scripts import route_bench


def test_capture_accepts_a_candidate_policy() -> None:
    signature = inspect.signature(route_bench.capture)
    assert "policy" in signature.parameters
    assert signature.parameters["policy"].default is CandidatePolicy.NO_PROLIFERATOR


def test_cli_parses_every_candidate_policy() -> None:
    parser = route_bench.build_parser()
    for policy in CandidatePolicy:
        parsed = parser.parse_args(["--capture", "graphene", "--policy", policy.value])
        assert parsed.policy is policy
