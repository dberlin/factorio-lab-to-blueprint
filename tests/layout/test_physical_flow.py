"""Exact certificates for fractional flows sharing physical resources."""

from fractions import Fraction

import pytest

from flab2bp.layout.physical_flow import Arc, Model, Resource, reuse_certificates, solve


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
    with reuse_certificates():
        assert solve(model, frozenset({"belt"})).feasible is True
        assert solve(model, frozenset({"sorter"})).feasible is True
        result = solve(model, frozenset({"belt", "sorter"}))
        assert solve(model, frozenset({"belt", "sorter"}), items=frozenset()).feasible is True
        assert solve(model, frozenset({"belt", "sorter"}), resources=frozenset()).feasible is True
        assert solve(triangle(Fraction(1)), frozenset({"belt", "sorter"})).feasible is True
        assert solve(model, frozenset({"belt", "sorter"})).feasible is False
    assert result.feasible is False
    assert result.upper_bound is not None
    assert result.upper_bound < result.required
    assert result.resource_prices[0] > 0
    assert result.resource_prices[2] > 0


@pytest.mark.parametrize(("source", "sink"), [(1, 0), (0, 1)])
def test_zero_lower_bound_does_not_hide_missing_endpoint(source: int, sink: int) -> None:
    model = Model(1, (Arc(source, sink, Fraction(1), "ore"),), ())
    with pytest.raises((IndexError, ValueError)):
        solve(model, frozenset())


def test_large_denominator_flow_is_certified_without_rounding_away_overload() -> None:
    rate = Fraction(1_000_000_008, 1_000_000_007)
    arcs = (
        Arc(0, 1, rate, "ore"),
        Arc(1, 0, rate, "ore", lower=rate),
    )
    feasible = Model(2, arcs, (Resource((0,), rate, "belt", (10,)),))
    result = solve(feasible, frozenset({"belt"}))
    assert result.feasible is True
    assert result.flows[0] == rate

    overloaded = Model(2, arcs, (Resource((0,), Fraction(1), "belt", (10,)),))
    result = solve(overloaded, frozenset({"belt"}))
    assert result.feasible is False
    assert result.upper_bound is not None
    assert result.upper_bound <= 1


@pytest.mark.parametrize("constrained", [False, True])
def test_conservation_certifies_merged_rates_with_large_common_denominator(
    constrained: bool,
) -> None:
    networks = (
        (Fraction(933489, 925), Fraction(441002, 141), Fraction(42451, 147)),
        (Fraction(37, 113), Fraction(41, 223), Fraction(43, 337)),
    )
    arcs: list[Arc] = []
    for network, rates in enumerate(networks):
        offset = 6 * network
        item = f"ore-{network}"
        total = sum(rates, Fraction(0))
        arcs.extend(
            (
                *(
                    Arc(offset, offset + i + 1, rate, item, lower=rate)
                    for i, rate in enumerate(rates)
                ),
                *(Arc(offset + i + 1, offset + 4, total, item) for i in range(3)),
                Arc(offset + 4, offset + 5, total, item),
                Arc(offset + 5, offset, total, item, lower=total),
            )
        )

    resources = (
        Resource(
            tuple(8 * network + 6 for network in range(len(networks))),
            sum((sum(rates, Fraction(0)) for rates in networks), Fraction(0)),
            "sorter",
            (10,),
        ),
    )
    result = solve(
        Model(nodes=12, arcs=tuple(arcs), resources=resources),
        frozenset({"sorter"}) if constrained else frozenset(),
    )

    assert result.feasible is True
    for network, rates in enumerate(networks):
        assert result.flows[8 * network + 3 : 8 * network + 6] == rates
        assert result.flows[8 * network + 6] == sum(rates, Fraction(0))
