"""Transport complete-power admission: real final-frame boundary cases."""

from collections.abc import Callable, Collection
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout import finalize, validate
from flab2bp.layout import routing_domain as rd
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.transport_routing.runtime import TransportRoutingKernel
from flab2bp.spec import BeltTier, BuildSpec, MachineGroup


@pytest.mark.parametrize("available_sites", [2, 3])
def test_complete_power_plan_revisits_site_after_required_prefix_changes(
    monkeypatch: pytest.MonkeyPatch, available_sites: int
) -> None:
    # With three sites, losing the deferred site strands the remaining demand.
    # With two, success occurs on the original loop's final permitted attempt.
    # Both must retain the original geometric-minimum portable band policy.
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="iron-ingot",
                machine_item_id="arc-smelter",
                count=1,
                inputs_per_machine={"iron-ore": Fraction(1)},
                outputs_per_machine={"iron-ingot": Fraction(1)},
            ),
        ),
        external_inputs={"iron-ore": Fraction(1)},
        outputs={"iron-ingot": Fraction(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
        belt_upgrades=(BeltTier(item_id="conveyor-belt-3", items_per_second=Fraction(30)),),
        sorter_item_ids=("sorter-1", "sorter-2", "sorter-3", "sorter-4"),
        sorter_pick_stacks=(1, 1, 1, 4),
        sorter_place_stacks=(1, 1, 1, 4),
        machine_rank="exact",
        power_tower_item_id="tesla-tower",
        piler_unlocked=True,
    )
    rules = catalog.BeltAltitudeRules(
        max_z=catalog.belt_max_z(catalog.DEFAULT_LAB_LEVEL),
        vertical_construction=True,
        storage_level=catalog.DEFAULT_STORAGE_LEVEL,
        lab_level=catalog.DEFAULT_LAB_LEVEL,
        from_url=False,
    )
    original = rd._power_plan
    trials: list[tuple[tuple[tuple[int, int], ...], finalize.ProjectionFailure | None]] = []

    def plan(
        canvas: rd._Canvas,
        demand: tuple[int, int, int, int],
        *,
        policy: BandPolicy,
        additional_demand: Collection[tuple[int, int]] = (),
        complete_plan_failure: Callable[
            [tuple[PlacedBuilding, ...]], finalize.ProjectionFailure | None
        ]
        | None = None,
        staged_static_cache: rd._StagedStaticCache | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[tuple[int, int]]:
        canvas.limit = (6, 9, 26, 15)
        allowed = {(17, 10), (26, 15)}
        if available_sites == 3:
            allowed.add((6, 9))
        canvas.keep_out.update(
            (x, y) for x in range(6, 27) for y in range(9, 16) if (x, y) not in allowed
        )
        assert complete_plan_failure is not None
        admit = complete_plan_failure

        def checked(
            towers: tuple[PlacedBuilding, ...],
        ) -> finalize.ProjectionFailure | None:
            # The admission callback is the real runtime cleanup/finalizer.
            failure = admit(towers)
            trials.append((tuple((b.x, b.y) for b in towers), failure))
            return failure

        return original(
            canvas,
            (10, 10, 25, 15),
            policy=policy,
            additional_demand=additional_demand,
            complete_plan_failure=checked,
            staged_static_cache=staged_static_cache,
            cancelled=cancelled,
        )

    monkeypatch.setattr(rd, "_power_plan", plan)
    placement = TransportRoutingKernel(
        belt_rules=rules, band_policy=BandPolicy("portable")
    ).lay_out(spec)
    report = validate.certify(placement, spec, belt_rules=rules, expect_power=True)
    assert report.ok and not report.skipped, (report.errors, report.skipped)
    assert placement.area == 120
    assert trials[0][0] == ((17, 10),) and trials[0][1] is not None
    assert trials[-1] == (((26, 15), (17, 10)), None)
