"""The post-routing pass that gives each belt run the cheapest tier it needs."""

from __future__ import annotations

from fractions import Fraction

from flab2bp.layout.base import Placement
from flab2bp.layout.belt_tiers import retier_belts
from flab2bp.layout.validate import IdMap, validate
from flab2bp.spec import BeltTier, BuildSpec, MachineGroup
from tests.layout.test_validate import (
    ASSEMBLER,
    BELT2,
    PILE,
    belt,
    fired,
    machine,
    place,
    sorter,
    splitter,
)

BELT1 = 2001
BELT3 = 2003
IDS = IdMap(recipes={"magnetic-coil": 6}, items={"assembling-machine-2": ASSEMBLER})


def _spec(
    rate: Fraction,
    *upgrades: tuple[str, int],
    belt_stack: int = 1,
    sorter_pick_stacks: tuple[int, ...] = (1, 1, 1, 2),
) -> BuildSpec:
    return BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=1,
                inputs_per_machine={"copper-ingot": rate},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        external_inputs={"copper-ingot": rate},
        outputs={"magnetic-coil": Fraction(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
        belt_upgrades=tuple(
            BeltTier(item_id=item_id, items_per_second=Fraction(speed))
            for item_id, speed in upgrades
        ),
        belt_stack=belt_stack,
        sorter_pick_stacks=sorter_pick_stacks,
    )


def _fed_machine_typed() -> Placement:
    """belt(2,0) -> belt(3,0) -> pile sorter -> assembler at (4,0).

    The definition; ``_fed_machine`` delegates to it so the two cannot drift.
    It exists separately because ``_fed_machine`` is unannotated and its dozen
    existing call sites are counted in this repo's 184-error mypy baseline: a
    new call to the untyped one would raise that number, and annotating it
    would lower it.  Tests added since call this one.
    """
    return place(
        belt(2, 0, out=1),
        belt(3, 0),
        machine(4, 0, recipe_id=6),
        sorter(3, 0, 4, 0, inp=1, out=2, item_id=PILE),
    )


def _fed_machine():
    return _fed_machine_typed()


def _tiers(placement) -> list[int]:
    return [b.item_id for b in placement.buildings if b.item_id in (BELT1, BELT2, BELT3)]


def test_a_run_within_the_floor_keeps_the_floor() -> None:
    out = retier_belts(_fed_machine(), _spec(Fraction(5), ("conveyor-belt-3", 30)))
    assert _tiers(out) == [BELT2, BELT2]
    assert out.stats["belt_runs_upgraded"] == 0.0


def test_a_run_over_the_floor_takes_the_cheapest_upgrade_that_fits() -> None:
    out = retier_belts(_fed_machine(), _spec(Fraction(14), ("conveyor-belt-3", 30)))
    assert _tiers(out) == [BELT3, BELT3]
    assert out.stats["belt_runs_upgraded"] == 1.0
    assert out.stats["belt_upgrade_tiers"] == ["conveyor-belt-3"]
    report = validate(out, _spec(Fraction(14), ("conveyor-belt-3", 30)), ids=IDS)
    assert not fired(report, "flow.belt_capacity")


def test_model_index_follows_the_tier() -> None:
    out = retier_belts(_fed_machine(), _spec(Fraction(14), ("conveyor-belt-3", 30)))
    assert {b.model_index for b in out.buildings if b.item_id == BELT3} == {37}


def test_a_run_over_the_ceiling_is_set_to_the_ceiling_and_still_refused() -> None:
    spec = _spec(Fraction(40), ("conveyor-belt-3", 30))
    out = retier_belts(_fed_machine(), spec)
    assert _tiers(out) == [BELT3, BELT3]
    assert fired(validate(out, spec, ids=IDS), "flow.belt_capacity")


def test_no_upgrades_leaves_the_placement_untouched() -> None:
    placement = _fed_machine()
    out = retier_belts(placement, _spec(Fraction(14)))
    assert out.buildings == placement.buildings


def test_a_trunk_feeding_two_branches_is_tiered_on_the_sum() -> None:
    """Two machines at 8/s each draw 16/s through the trunk into the splitter,
    so the trunk needs Mk.III while each branch fits Mk.II."""
    spec = BuildSpec(
        groups=(
            MachineGroup(
                recipe_id="magnetic-coil",
                machine_item_id="assembling-machine-2",
                count=2,
                inputs_per_machine={"copper-ingot": Fraction(8)},
                outputs_per_machine={"magnetic-coil": Fraction(1)},
            ),
        ),
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=Fraction(12),
        belt_upgrades=(BeltTier(item_id="conveyor-belt-3", items_per_second=Fraction(30)),),
    )
    placement = place(
        belt(0, 0, out=1),  # 0 trunk
        belt(1, 0, out=2),  # 1 trunk, feeds the splitter
        splitter(2, 0),  # 2
        belt(3, 0, inp=2, out=4),  # 3 branch north
        belt(4, 0),  # 4
        belt(2, 1, inp=2, out=6),  # 5 branch south
        belt(2, 2),  # 6
        machine(5, 0, recipe_id=6),  # 7
        machine(2, 3, recipe_id=6),  # 8
        sorter(4, 0, 5, 0, inp=4, out=7, item_id=PILE),  # 9
        sorter(2, 2, 2, 3, inp=6, out=8, item_id=PILE),  # 10
    )
    out = retier_belts(placement, spec)
    by_index = {i: b.item_id for i, b in enumerate(out.buildings)}
    assert by_index[0] == BELT3 and by_index[1] == BELT3
    assert by_index[3] == BELT2 and by_index[4] == BELT2
    assert by_index[5] == BELT2 and by_index[6] == BELT2


def test_a_stacked_run_is_measured_in_cargo_not_items() -> None:
    """20 items/s is 10 cargo/s when each cargo holds two, and a Mk.II belt
    carries 12 cargo/s -- so the same lane that needs a Mk.III loose fits the
    floor stacked, and the pass must not pay for the upgrade."""
    stacked = _spec(Fraction(20), ("conveyor-belt-3", 30), belt_stack=2)
    out = retier_belts(_fed_machine_typed(), stacked)
    assert _tiers(out) == [BELT2, BELT2]
    assert out.stats["belt_runs_upgraded"] == 0.0


def test_the_same_run_unstacked_still_takes_the_upgrade() -> None:
    """The other half of the pair: without the URL's stack, 20 items/s is 20
    cargo/s and the floor cannot carry it."""
    out = retier_belts(_fed_machine_typed(), _spec(Fraction(20), ("conveyor-belt-3", 30)))
    assert _tiers(out) == [BELT3, BELT3]
    assert out.stats["belt_runs_upgraded"] == 1.0


def test_a_stacked_run_over_the_ceiling_is_still_set_to_the_ceiling() -> None:
    """The fall-through has to survive the division: 80 items/s at stack 2 is
    40 cargo/s, over the 30/s ceiling, so the run ends on the ceiling and
    `flow.belt_capacity` refuses it rather than this pass inventing a tier."""
    stacked = _spec(Fraction(80), ("conveyor-belt-3", 30), belt_stack=2)
    out = retier_belts(_fed_machine_typed(), stacked)
    assert _tiers(out) == [BELT3, BELT3]
