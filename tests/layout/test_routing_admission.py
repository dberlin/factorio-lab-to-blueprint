"""Early route evidence is narrower than final factory certification."""

from collections.abc import Iterable
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout import physical_flow
from flab2bp.layout import validate as validation
from flab2bp.layout.base import Placement
from tests.layout.test_validate import belt, ore_spec, shared_lane, two_consumer_spec

BELT_RULES = catalog.belt_rules_for_technologies(None, frozenset())


def enclosed_entry(*, gap: bool = False) -> tuple[Placement, frozenset[int]]:
    # Eight linked tiles in one trapped pocket. The distant wall, rather than
    # merely the entry's immediate neighbors, is what prevents player access.
    buildings = [
        belt(x, 3, out=x - 2 if x < 10 else None, carries="copper-ore") for x in range(3, 11)
    ]
    frontier: set[int] = set(range(len(buildings)))
    for x in range(15):
        for y in range(7):
            if x not in (0, 14) and y not in (0, 6):
                continue
            if gap and (x, y) == (0, 3):
                continue
            # Corner cells do not touch the enclosed four-neighbor pocket.
            if (x not in (0, 14)) or (y not in (0, 6)):
                frontier.add(len(buildings))
            buildings.append(belt(x, y))
    buildings.append(belt(25, 25))  # unrelated, not a cause of the refusal
    return Placement(buildings=tuple(buildings)), frozenset(frontier)


def test_trapped_entry_support_contains_complete_pocket_frontier_and_run() -> None:
    placement, expected = enclosed_entry()
    failures = validation.routing_admission(placement, ore_spec(), belt_rules=BELT_RULES)
    assert failures is not None
    entry = [
        failure for failure in failures if failure.finding.check == "flow.external_entry_reachable"
    ]
    assert len(entry) == 1
    assert entry[0].support == expected
    assert len(entry[0].finding.buildings) < len(expected)


def test_opening_distant_frontier_makes_inland_entry_admissible() -> None:
    placement, _ = enclosed_entry(gap=True)
    failures = validation.routing_admission(placement, ore_spec(), belt_rules=BELT_RULES)
    assert failures == ()


def test_admission_rejects_joint_item_load_with_unknown_capacity_support() -> None:
    failures = validation.routing_admission(
        shared_lane(), two_consumer_spec(Fraction(7), Fraction(7)), belt_rules=BELT_RULES
    )
    assert failures is not None
    capacity = [failure for failure in failures if failure.finding.check == "flow.belt_capacity"]
    assert len(capacity) == 1
    assert Fraction(str(capacity[0].finding.detail["shortfall"])) > 0
    # Resource prices identify bottlenecks, not all owners fixing that flow.
    assert capacity[0].support is None


def test_admission_accepts_shared_load_at_capacity_without_certifying_factory() -> None:
    placement = shared_lane()
    spec = two_consumer_spec(Fraction(6), Fraction(6))
    assert validation.routing_admission(placement, spec, belt_rules=BELT_RULES) == ()
    report = validation.certify(placement, spec, belt_rules=BELT_RULES, expect_power=True)
    assert report.by_check("power.coverage")
    assert not report.ok


def test_cancellation_before_admission_returns_unknown() -> None:
    placement, _ = enclosed_entry()
    assert (
        validation.routing_admission(
            placement, ore_spec(), belt_rules=BELT_RULES, cancelled=lambda: True
        )
        is None
    )


def test_cancellation_during_exterior_flood_returns_unknown() -> None:
    placement, _ = enclosed_entry()
    remaining = 20

    def cancelled() -> bool:
        nonlocal remaining
        remaining -= 1
        return remaining <= 0

    assert (
        validation.routing_admission(
            placement, ore_spec(), belt_rules=BELT_RULES, cancelled=cancelled
        )
        is None
    )
    assert remaining <= 0


def test_cancellation_after_finding_discards_partial_refusals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placement, _ = enclosed_entry()
    original = validation._belt_capacity
    cancelled = False

    def cancel_after_capacity(ctx: validation.Context) -> Iterable[validation.Finding]:
        nonlocal cancelled
        yield from original(ctx)
        cancelled = True

    monkeypatch.setattr(validation, "_belt_capacity", cancel_after_capacity)
    assert (
        validation.routing_admission(
            placement, ore_spec(), belt_rules=BELT_RULES, cancelled=lambda: cancelled
        )
        is None
    )
    assert cancelled


def test_uncertified_native_flow_is_unknown_not_a_capacity_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def inconclusive(
        model: physical_flow.Model,
        kinds: frozenset[physical_flow.ResourceKind],
        *,
        items: frozenset[str] | None = None,
        resources: frozenset[int] | None = None,
    ) -> physical_flow.Result:
        return physical_flow.Result(
            feasible=None,
            required=Fraction(12),
            upper_bound=None,
            flows=(),
            resource_prices=(Fraction(0),) * len(model.resources),
        )

    monkeypatch.setattr(physical_flow, "solve", inconclusive)
    assert (
        validation.routing_admission(
            shared_lane(), two_consumer_spec(Fraction(6), Fraction(6)), belt_rules=BELT_RULES
        )
        is None
    )
