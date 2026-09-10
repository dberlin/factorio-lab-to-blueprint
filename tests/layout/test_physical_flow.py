"""Exact certificates for fractional flows sharing physical resources."""

from fractions import Fraction

from flab2bp.layout.physical_flow import Arc, Model, Resource, solve


def triangle(capacity: Fraction) -> Model:
    # Three route choices share resources pairwise. Meeting 3/2 requires
    # 1/2 on every route; testing each resource independently is unsound.
    return Model(
        nodes=2,
        arcs=(
            *(Arc(0, 1, Fraction(1), "ore") for _ in range(3)),
            Arc(1, 0, Fraction(3, 2), "ore", lower=Fraction(3, 2)),
        ),
        resources=(
            Resource((0, 1), capacity, "belt", (10,)),
            Resource((0, 2), Fraction(1), "belt", (11,)),
            Resource((1, 2), Fraction(1), "sorter", (12,)),
        ),
    )


def test_shared_resources_allow_fractional_route_allocation() -> None:
    result = solve(triangle(Fraction(1)), frozenset({"belt", "sorter"}))
    assert result.feasible is True
    assert result.flows[:3] == (Fraction(1, 2),) * 3


def test_joint_capacity_refusal_has_an_exact_shortfall_certificate() -> None:
    model = triangle(Fraction(3, 4))
    assert solve(model, frozenset({"belt"})).feasible is True
    assert solve(model, frozenset({"sorter"})).feasible is True
    result = solve(model, frozenset({"belt", "sorter"}))
    assert result.feasible is False
    assert result.upper_bound is not None
    assert result.upper_bound < result.required
    assert result.resource_prices[0] > 0
    assert result.resource_prices[2] > 0
